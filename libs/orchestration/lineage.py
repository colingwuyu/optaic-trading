"""Lineage resolution for resource dependencies.

Provides dependency tracking and resolution using the dataset_lineage table:
- Resolve upstream dependencies (what this resource depends on)
- Resolve downstream dependencies (what depends on this resource)
- Check freshness of all upstream dependencies before execution
- Get topologically sorted execution order for DAG execution
- Propagate staleness when upstream changes

This is the core of the "smart execution" feature where we:
- Block or warn if upstream dependencies are stale/error
- Calculate execution order for complex DAGs
- Invalidate downstream caches when upstream changes

Ported from: optaic-v0/dev_tools/src/data/api.py (lineage logic)
             optaic-v0/dev_tools/src/core/dag.py (graph traversal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .freshness import DatasetStatus, FreshnessChecker


@dataclass
class LineageFreshnessReport:
    """Report on freshness of a resource's upstream dependencies."""

    resource_id: UUID
    all_ready: bool
    blocking_resources: list[UUID] = field(default_factory=list)
    status_map: dict[UUID, "DatasetStatus"] = field(default_factory=dict)


class UpstreamNotReadyError(Exception):
    """Raised when upstream dependencies are not ready for execution."""

    def __init__(
        self,
        message: str,
        blocking_resources: list[UUID],
    ) -> None:
        self.blocking_resources = blocking_resources
        super().__init__(message)


class LineageResolver:
    """Resolves resource dependencies using dataset_lineage table.

    The LineageResolver provides methods to:
    - Traverse the dependency graph (upstream and downstream)
    - Check freshness of all dependencies before execution
    - Calculate topologically sorted execution order
    - Propagate staleness when upstream resources change

    Example usage:
        resolver = LineageResolver()

        # Get all upstream dependencies
        upstreams = await resolver.resolve_upstream_dependencies(
            session, resource_id, recursive=True
        )

        # Check if all dependencies are ready
        report = await resolver.check_upstream_freshness(
            session, resource_id, freshness_checker
        )

        if not report.all_ready:
            raise UpstreamNotReadyError(
                f"{len(report.blocking_resources)} upstreams not ready",
                report.blocking_resources
            )

        # Get execution order for DAG
        batches = await resolver.get_execution_order(session, root_id)
    """

    async def resolve_upstream_dependencies(
        self,
        session: "AsyncSession",
        resource_id: UUID,
        *,
        recursive: bool = True,
    ) -> list[UUID]:
        """Get all upstream dependencies for a resource.

        Args:
            session: Database session
            resource_id: Resource ID to find dependencies for
            recursive: If True, find transitive dependencies

        Returns:
            List of upstream resource IDs (in dependency order if recursive)
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        if not recursive:
            # Just direct dependencies
            stmt = select(DatasetLineage.upstream_resource_id).where(
                DatasetLineage.downstream_resource_id == resource_id
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        # Recursive traversal using BFS
        visited: set[UUID] = set()
        ordered: list[UUID] = []
        queue = [resource_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            # Get direct upstreams
            stmt = select(DatasetLineage.upstream_resource_id).where(
                DatasetLineage.downstream_resource_id == current_id
            )
            result = await session.execute(stmt)
            upstreams = list(result.scalars().all())

            for upstream_id in upstreams:
                if upstream_id not in visited:
                    queue.append(upstream_id)
                    ordered.append(upstream_id)

        return ordered

    async def resolve_downstream_dependencies(
        self,
        session: "AsyncSession",
        resource_id: UUID,
        *,
        recursive: bool = True,
    ) -> list[UUID]:
        """Get all downstream dependents for a resource.

        Args:
            session: Database session
            resource_id: Resource ID to find dependents for
            recursive: If True, find transitive dependents

        Returns:
            List of downstream resource IDs
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        if not recursive:
            # Just direct dependents
            stmt = select(DatasetLineage.downstream_resource_id).where(
                DatasetLineage.upstream_resource_id == resource_id
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

        # Recursive traversal using BFS
        visited: set[UUID] = set()
        ordered: list[UUID] = []
        queue = [resource_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            # Get direct downstreams
            stmt = select(DatasetLineage.downstream_resource_id).where(
                DatasetLineage.upstream_resource_id == current_id
            )
            result = await session.execute(stmt)
            downstreams = list(result.scalars().all())

            for downstream_id in downstreams:
                if downstream_id not in visited:
                    queue.append(downstream_id)
                    ordered.append(downstream_id)

        return ordered

    async def check_upstream_freshness(
        self,
        session: "AsyncSession",
        resource_id: UUID,
        freshness_checker: "FreshnessChecker",
    ) -> LineageFreshnessReport:
        """Check freshness of all upstream dependencies.

        Args:
            session: Database session
            resource_id: Resource ID to check dependencies for
            freshness_checker: FreshnessChecker for calculating staleness

        Returns:
            FreshnessReport with:
            - all_ready: True if all upstreams are fresh
            - blocking_resources: List of stale/error upstream IDs
            - status_map: Status of each upstream
        """
        from .freshness import DatasetStatus

        upstreams = await self.resolve_upstream_dependencies(
            session, resource_id, recursive=True
        )

        status_map: dict[UUID, DatasetStatus] = {}
        blocking_resources: list[UUID] = []

        for upstream_id in upstreams:
            status = await freshness_checker.calculate_staleness(session, upstream_id)
            status_map[upstream_id] = status

            if status != DatasetStatus.READY:
                blocking_resources.append(upstream_id)

        return LineageFreshnessReport(
            resource_id=resource_id,
            all_ready=len(blocking_resources) == 0,
            blocking_resources=blocking_resources,
            status_map=status_map,
        )

    async def get_execution_order(
        self,
        session: "AsyncSession",
        root_id: UUID,
    ) -> list[list[UUID]]:
        """Get topologically sorted execution order as batches.

        Each batch can run in parallel; batches execute sequentially.
        Earlier batches have no dependencies; later batches depend on earlier ones.

        Args:
            session: Database session
            root_id: Root resource to build execution order from

        Returns:
            List of batches, where each batch is a list of resource IDs
            that can execute in parallel
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        # Build the dependency graph
        all_resources = await self.resolve_upstream_dependencies(
            session, root_id, recursive=True
        )
        all_resources.append(root_id)  # Include root

        # Get all edges
        stmt = select(
            DatasetLineage.upstream_resource_id, DatasetLineage.downstream_resource_id
        ).where(DatasetLineage.downstream_resource_id.in_(all_resources))
        result = await session.execute(stmt)
        edges = list(result.all())

        # Build adjacency lists
        dependencies: dict[UUID, set[UUID]] = {r: set() for r in all_resources}
        for upstream, downstream in edges:
            if downstream in dependencies:
                dependencies[downstream].add(upstream)

        # Kahn's algorithm for topological sort with batching
        in_degree: dict[UUID, int] = {r: len(deps) for r, deps in dependencies.items()}
        batches: list[list[UUID]] = []

        while in_degree:
            # Find all nodes with no dependencies
            batch = [r for r, deg in in_degree.items() if deg == 0]

            if not batch:
                # Cycle detected - shouldn't happen with valid data
                raise ValueError("Cycle detected in dependency graph")

            batches.append(batch)

            # Remove batch nodes and update degrees
            for r in batch:
                del in_degree[r]
                # Reduce in-degree of dependents
                for other, deps in dependencies.items():
                    if r in deps:
                        in_degree[other] -= 1

        return batches

    async def propagate_staleness(
        self,
        session: "AsyncSession",
        resource_id: UUID,
    ) -> list[UUID]:
        """Mark downstream dependents as stale when upstream changes.

        This should be called when:
        - A dataset is refreshed with new data
        - A pipeline definition changes
        - An upstream resource is invalidated

        Args:
            session: Database session
            resource_id: Resource ID that changed

        Returns:
            List of affected downstream resource IDs
        """
        from libs.db.models.quant import DatasetInstance

        downstreams = await self.resolve_downstream_dependencies(
            session, resource_id, recursive=True
        )

        affected: list[UUID] = []
        for downstream_id in downstreams:
            dataset = await session.get(DatasetInstance, downstream_id)
            if dataset and dataset.freshness_status != "stale":
                dataset.freshness_status = "stale"
                affected.append(downstream_id)

        if affected:
            await session.flush()

        return affected

    async def add_lineage_edge(
        self,
        session: "AsyncSession",
        tenant_id: UUID,
        upstream_id: UUID,
        downstream_id: UUID,
        edge_kind: str = "data_dependency",
    ) -> None:
        """Add a lineage edge between two resources.

        Args:
            session: Database session
            tenant_id: Tenant ID
            upstream_id: Upstream resource ID
            downstream_id: Downstream resource ID
            edge_kind: Type of dependency ("data_dependency", "schema_dependency", etc.)
        """
        from libs.db.models.quant import DatasetLineage

        edge = DatasetLineage(
            tenant_id=tenant_id,
            upstream_resource_id=upstream_id,
            downstream_resource_id=downstream_id,
            edge_kind=edge_kind,
        )
        session.add(edge)

    async def remove_lineage_edge(
        self,
        session: "AsyncSession",
        upstream_id: UUID,
        downstream_id: UUID,
    ) -> bool:
        """Remove a lineage edge between two resources.

        Args:
            session: Database session
            upstream_id: Upstream resource ID
            downstream_id: Downstream resource ID

        Returns:
            True if edge was removed, False if not found
        """
        from sqlalchemy import delete

        from libs.db.models.quant import DatasetLineage

        stmt = delete(DatasetLineage).where(
            DatasetLineage.upstream_resource_id == upstream_id,
            DatasetLineage.downstream_resource_id == downstream_id,
        )
        result = await session.execute(stmt)
        return result.rowcount > 0

    async def get_lineage_graph(
        self,
        session: "AsyncSession",
        resource_id: UUID,
        *,
        direction: str = "both",
        max_depth: Optional[int] = None,
    ) -> dict:
        """Get the lineage graph for a resource.

        Args:
            session: Database session
            resource_id: Center resource ID
            direction: "upstream", "downstream", or "both"
            max_depth: Maximum depth to traverse (None for unlimited)

        Returns:
            Dict with nodes and edges for visualization
        """
        from libs.db.models.resource import Resource

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        # Get resources based on direction
        if direction in ("upstream", "both"):
            upstreams = await self.resolve_upstream_dependencies(
                session, resource_id, recursive=True
            )
            for uid in upstreams:
                resource = await session.get(Resource, uid)
                if resource:
                    nodes[str(uid)] = {
                        "id": str(uid),
                        "name": resource.name,
                        "type": resource.type,
                        "direction": "upstream",
                    }

        if direction in ("downstream", "both"):
            downstreams = await self.resolve_downstream_dependencies(
                session, resource_id, recursive=True
            )
            for did in downstreams:
                resource = await session.get(Resource, did)
                if resource:
                    nodes[str(did)] = {
                        "id": str(did),
                        "name": resource.name,
                        "type": resource.type,
                        "direction": "downstream",
                    }

        # Add center node
        center = await session.get(Resource, resource_id)
        if center:
            nodes[str(resource_id)] = {
                "id": str(resource_id),
                "name": center.name,
                "type": center.type,
                "direction": "center",
            }

        # Get all edges between these nodes
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        node_ids = [UUID(nid) for nid in nodes.keys()]
        stmt = select(DatasetLineage).where(
            DatasetLineage.upstream_resource_id.in_(node_ids),
            DatasetLineage.downstream_resource_id.in_(node_ids),
        )
        result = await session.execute(stmt)
        for row in result.scalars().all():
            edges.append(
                {
                    "source": str(row.upstream_resource_id),
                    "target": str(row.downstream_resource_id),
                    "kind": row.edge_kind,
                }
            )

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "center_id": str(resource_id),
        }

    async def build_dag_for_instance(
        self,
        session: "AsyncSession",
        instance_id: UUID,
        tenant_id: UUID,
    ) -> "LineageDAG":
        """Build dependency DAG when a flow resource is created.

        Parses the instance configuration to extract upstream dependencies.
        For DatasetInstances, this looks at the pipeline config.
        For ExperimentInstances, this looks at input_datasets_json.

        Args:
            session: Database session
            instance_id: Instance resource ID
            tenant_id: Tenant ID

        Returns:
            LineageDAG with upstream_ids, ready for storage and subscription creation
        """
        from libs.db.models.quant import (
            DatasetInstance,
            ExperimentInstance,
            PipelineInstance,
        )

        upstream_ids: list[UUID] = []

        # Check if it's a DatasetInstance
        dataset_instance = await session.get(DatasetInstance, instance_id)
        if dataset_instance:
            # Get pipeline instance to extract dependencies from config
            pipeline_instance = await session.get(
                PipelineInstance, dataset_instance.pipeline_instance_id
            )
            if pipeline_instance:
                upstream_ids = self._extract_upstream_from_pipeline_config(
                    pipeline_instance.config_json
                )

        # Check if it's an ExperimentInstance
        experiment_instance = await session.get(ExperimentInstance, instance_id)
        if experiment_instance:
            # input_datasets_json maps alias -> dataset_id
            for dataset_id in experiment_instance.input_datasets_json.values():
                if dataset_id:
                    try:
                        upstream_ids.append(UUID(str(dataset_id)))
                    except (ValueError, TypeError):
                        pass

        return LineageDAG(
            instance_id=instance_id,
            tenant_id=tenant_id,
            upstream_ids=upstream_ids,
        )

    def _extract_upstream_from_pipeline_config(
        self,
        config: dict,
    ) -> list[UUID]:
        """Extract upstream dataset IDs from pipeline configuration.

        Supports multiple config patterns:
        - input_datasets: list of dataset IDs
        - upstream_datasets: list of dataset IDs
        - expression_inputs: dict mapping alias to dataset ID
        - sources: list of source configs with dataset_id field

        Args:
            config: Pipeline configuration dict

        Returns:
            List of upstream dataset UUIDs
        """
        upstream_ids: list[UUID] = []

        # Pattern 1: input_datasets list
        if "input_datasets" in config:
            for dataset_id in config["input_datasets"]:
                try:
                    upstream_ids.append(UUID(str(dataset_id)))
                except (ValueError, TypeError):
                    pass

        # Pattern 2: upstream_datasets list
        if "upstream_datasets" in config:
            for dataset_id in config["upstream_datasets"]:
                try:
                    upstream_ids.append(UUID(str(dataset_id)))
                except (ValueError, TypeError):
                    pass

        # Pattern 3: expression_inputs dict (alias -> dataset_id)
        if "expression_inputs" in config:
            for dataset_id in config["expression_inputs"].values():
                try:
                    upstream_ids.append(UUID(str(dataset_id)))
                except (ValueError, TypeError):
                    pass

        # Pattern 4: sources list with dataset_id
        if "sources" in config:
            for source in config["sources"]:
                if isinstance(source, dict) and "dataset_id" in source:
                    try:
                        upstream_ids.append(UUID(str(source["dataset_id"])))
                    except (ValueError, TypeError):
                        pass

        return upstream_ids

    async def create_lineage_and_subscriptions(
        self,
        session: "AsyncSession",
        dag: "LineageDAG",
    ) -> None:
        """Create lineage records and subscriptions for upstream dependencies.

        This should be called when a flow resource is created. It:
        1. Creates DatasetLineage records for each upstream dependency
        2. Creates Subscription records so downstream gets notified on completion

        Args:
            session: Database session
            dag: LineageDAG from build_dag_for_instance()
        """
        from libs.db.models.quant import DatasetLineage
        from libs.db.models.subscription import Subscription

        for upstream_id in dag.upstream_ids:
            # Create lineage edge
            lineage = DatasetLineage(
                tenant_id=dag.tenant_id,
                upstream_resource_id=upstream_id,
                downstream_resource_id=dag.instance_id,
                edge_kind="data_dependency",
            )
            session.add(lineage)

            # Create subscription for completion events
            # The downstream instance "subscribes" to the upstream's completion
            subscription = Subscription(
                tenant_id=dag.tenant_id,
                principal_id=dag.instance_id,  # Using instance_id as principal for resource-level subscriptions
                resource_id=upstream_id,
                scope="completion",  # Subscribe to completion events
            )
            session.add(subscription)

    async def update_upstream_status(
        self,
        session: "AsyncSession",
        downstream_id: UUID,
        upstream_id: UUID,
        status: str,
    ) -> bool:
        """Update the status of an upstream dependency.

        Called by the observer when an upstream completes or fails.

        Args:
            session: Database session
            downstream_id: Downstream instance ID
            upstream_id: Upstream instance ID that changed
            status: New status ("ready", "stale", "running", "error")

        Returns:
            True if all upstreams are now ready
        """
        from libs.db.models.quant import DatasetInstance

        instance = await session.get(DatasetInstance, downstream_id)
        if not instance:
            return False

        # Update upstream status
        upstream_status = instance.upstream_status or {}
        upstream_status[str(upstream_id)] = status
        instance.upstream_status = upstream_status

        # Check if all upstreams are ready
        upstream_ids = instance.upstream_resource_ids or []
        all_ready = all(
            upstream_status.get(str(uid)) == "ready" for uid in upstream_ids
        )

        return all_ready

    async def check_all_upstreams_ready(
        self,
        session: "AsyncSession",
        instance_id: UUID,
    ) -> bool:
        """Check if all upstream dependencies are ready.

        This reads from the cached upstream_status on the instance,
        not from the lineage table - making execution checks fast.

        Args:
            session: Database session
            instance_id: Instance ID to check

        Returns:
            True if all upstreams are ready
        """
        from libs.db.models.quant import DatasetInstance

        instance = await session.get(DatasetInstance, instance_id)
        if not instance:
            return False

        upstream_ids = instance.upstream_resource_ids or []
        if not upstream_ids:
            return True  # No dependencies means always ready

        upstream_status = instance.upstream_status or {}
        return all(upstream_status.get(str(uid)) == "ready" for uid in upstream_ids)


@dataclass
class LineageDAG:
    """Represents a lineage DAG for an instance.

    Built at instance creation time and used to:
    - Store upstream_ids on the instance
    - Create DatasetLineage records
    - Create Subscription records for pub/sub
    """

    instance_id: UUID
    tenant_id: UUID
    upstream_ids: list[UUID] = field(default_factory=list)

    @property
    def has_dependencies(self) -> bool:
        """Check if this DAG has any upstream dependencies."""
        return len(self.upstream_ids) > 0
