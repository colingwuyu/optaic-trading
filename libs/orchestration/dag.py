"""Dependency Graph for execution orchestration.

Ported from: optaic-v0/dev_tools/src/core/dag.py
Adapted to use Resource IDs instead of name-based catalog lookup.

This module provides:
- DependencyGraph: A graph structure for execution dependencies
- build_graph(): Build a dependency graph from a root resource

The DAG is used by orchestrators to determine execution order and
to track which upstream resources need to be refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class NodeData:
    """Data associated with a node in the dependency graph."""

    resource_id: UUID
    name: str
    resource_type: str  # "DatasetInstance", "SignalInstance", etc.
    code_ref: Optional[str] = None  # Pipeline/accessor code_ref
    config: dict[str, Any] = field(default_factory=dict)

    # Status information
    status: str = "unknown"  # "fresh", "stale", "unknown", "error"
    last_run_at: Optional[datetime] = None
    last_data_date: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass
class GraphNode:
    """A node in the dependency graph."""

    id: str  # Node ID (string UUID for serialization)
    label: str  # Human-readable label
    type: str  # Resource type
    data: NodeData


@dataclass
class GraphEdge:
    """An edge in the dependency graph.

    Direction: source -> target (upstream -> downstream)
    """

    source: str  # Source node ID (upstream)
    target: str  # Target node ID (downstream)


class DependencyGraph:
    """Dependency graph for execution orchestration.

    Builds a directed acyclic graph (DAG) of resource dependencies,
    where edges point from upstream (dependency) to downstream (dependent).

    Example:
        graph = DependencyGraph()
        graph.add_node(dataset_instance, status_record)
        graph.add_node(upstream_dataset, status_record)
        graph.add_edge(upstream_id, dataset_id)

        # Serialize for orchestrator
        flow_def = graph.to_dict()
    """

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []

    def add_node(
        self,
        resource_id: UUID,
        name: str,
        resource_type: str,
        *,
        code_ref: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
        status: str = "unknown",
        last_run_at: Optional[datetime] = None,
        last_data_date: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Add a node to the graph.

        Args:
            resource_id: The Resource ID
            name: Human-readable name
            resource_type: Type of resource (DatasetInstance, etc.)
            code_ref: Optional code reference for execution
            config: Optional configuration dict
            status: Freshness status (fresh, stale, unknown, error)
            last_run_at: When the resource was last executed
            last_data_date: Latest data date in the resource
            error_message: Error message if status is 'error'
        """
        node_id = str(resource_id)

        if node_id in self.nodes:
            return  # Already added

        node_data = NodeData(
            resource_id=resource_id,
            name=name,
            resource_type=resource_type,
            code_ref=code_ref,
            config=config or {},
            status=status,
            last_run_at=last_run_at,
            last_data_date=last_data_date,
            error_message=error_message,
        )

        self.nodes[node_id] = GraphNode(
            id=node_id,
            label=name,
            type=resource_type,
            data=node_data,
        )

    def add_edge(self, source_id: UUID, target_id: UUID) -> None:
        """Add an edge from upstream to downstream.

        Args:
            source_id: Upstream resource ID (dependency)
            target_id: Downstream resource ID (dependent)
        """
        source_str = str(source_id)
        target_str = str(target_id)

        # Validate both nodes exist
        if source_str not in self.nodes:
            raise ValueError(f"Source node {source_id} not in graph")
        if target_str not in self.nodes:
            raise ValueError(f"Target node {target_id} not in graph")

        # Add edge (direction: upstream -> downstream)
        self.edges.append(GraphEdge(source=source_str, target=target_str))

    def get_node(self, resource_id: UUID) -> Optional[GraphNode]:
        """Get a node by resource ID."""
        return self.nodes.get(str(resource_id))

    def get_upstream(self, resource_id: UUID) -> list[GraphNode]:
        """Get all direct upstream dependencies of a node."""
        node_id = str(resource_id)
        upstream_ids = [edge.source for edge in self.edges if edge.target == node_id]
        return [self.nodes[uid] for uid in upstream_ids if uid in self.nodes]

    def get_downstream(self, resource_id: UUID) -> list[GraphNode]:
        """Get all direct downstream dependents of a node."""
        node_id = str(resource_id)
        downstream_ids = [edge.target for edge in self.edges if edge.source == node_id]
        return [self.nodes[did] for did in downstream_ids if did in self.nodes]

    def get_stale_nodes(self) -> list[GraphNode]:
        """Get all nodes with stale or unknown status."""
        return [
            node
            for node in self.nodes.values()
            if node.data.status in ("stale", "unknown")
        ]

    def get_execution_order(self) -> list[list[str]]:
        """Get nodes in topological order for execution.

        Returns a list of batches, where each batch can be executed
        in parallel, and batches must be executed sequentially.

        Returns:
            List of batches, each batch is a list of node IDs
        """
        from graphlib import TopologicalSorter

        # Build dependency dict for TopologicalSorter
        # Each node maps to its dependencies (upstream nodes)
        deps: dict[str, set[str]] = {node_id: set() for node_id in self.nodes}
        for edge in self.edges:
            # edge.target depends on edge.source
            deps[edge.target].add(edge.source)

        sorter = TopologicalSorter(deps)
        sorter.prepare()

        batches: list[list[str]] = []
        while sorter.is_active():
            ready = list(sorter.get_ready())
            if not ready:
                break
            batches.append(ready)
            for node_id in ready:
                sorter.done(node_id)

        return batches

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph to dict for orchestrator.

        Returns:
            Dict with 'nodes' and 'edges' keys suitable for
            passing to OrchestratorAdapter.submit_run()
        """
        return {
            "nodes": [
                {
                    "id": node.id,
                    "label": node.label,
                    "type": node.type,
                    "resource_id": str(node.data.resource_id),
                    "code_ref": node.data.code_ref,
                    "config": node.data.config,
                    "status": node.data.status,
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {"source": edge.source, "target": edge.target} for edge in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DependencyGraph":
        """Deserialize graph from dict.

        Args:
            data: Dict with 'nodes' and 'edges' keys

        Returns:
            DependencyGraph instance
        """
        graph = cls()

        for node_data in data.get("nodes", []):
            graph.add_node(
                resource_id=UUID(node_data["resource_id"]),
                name=node_data["label"],
                resource_type=node_data["type"],
                code_ref=node_data.get("code_ref"),
                config=node_data.get("config", {}),
                status=node_data.get("status", "unknown"),
            )

        for edge_data in data.get("edges", []):
            # Edges store string IDs, reconstruct UUIDs
            source = UUID(edge_data["source"])
            target = UUID(edge_data["target"])
            graph.add_edge(source, target)

        return graph


async def build_graph(
    session: "AsyncSession",
    root_id: UUID,
    tenant_id: UUID,
    *,
    include_status: bool = True,
    max_depth: int = 10,
) -> DependencyGraph:
    """Build a dependency graph starting from a root resource.

    Crawls the resource lineage to build a complete dependency graph,
    optionally including freshness status for each node.

    Args:
        session: Database session
        root_id: Root resource ID to start from
        tenant_id: Tenant ID for resource lookup
        include_status: Whether to fetch status for each node
        max_depth: Maximum recursion depth (prevents infinite loops)

    Returns:
        DependencyGraph with all dependencies

    Example:
        graph = await build_graph(session, dataset_id, tenant_id)
        flow_def = graph.to_dict()
        await orchestrator.submit_run(run_id, flow_def, config, tags)
    """
    from libs.db.models.resource import Resource
    from libs.db.models.quant import DatasetInstance

    from .status_store import StatusStore

    graph = DependencyGraph()
    visited: set[UUID] = set()

    # Initialize status store for status lookup
    status_store = StatusStore(session)

    async def crawl(resource_id: UUID, depth: int = 0) -> None:
        """Recursively crawl dependencies."""
        if depth > max_depth:
            return

        if resource_id in visited:
            return
        visited.add(resource_id)

        # Load resource
        resource = await session.get(Resource, resource_id)
        if not resource or resource.tenant_id != tenant_id:
            return

        # Get status if requested
        status = "unknown"
        last_run_at = None
        last_data_date = None
        error_message = None
        code_ref = None
        config: dict[str, Any] = {}

        # Check if this is a DatasetInstance
        if resource.type == "DatasetInstance":
            dataset = await session.get(DatasetInstance, resource_id)
            if dataset:
                status = dataset.freshness_status or "unknown"
                last_data_date = dataset.last_data_date
                # Get code_ref from associated pipeline definition
                # (loaded via pipeline_instance -> pipeline_definition)
                if include_status:
                    status_record = await status_store.get_status(resource_id)
                    if status_record:
                        last_run_at = status_record.last_pipeline_run
                        error_message = status_record.error_message

        # Add node to graph
        graph.add_node(
            resource_id=resource_id,
            name=resource.name,
            resource_type=resource.type,
            code_ref=code_ref,
            config=config,
            status=status,
            last_run_at=last_run_at,
            last_data_date=last_data_date,
            error_message=error_message,
        )

        # Find upstream dependencies via dataset_lineage
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        stmt = select(DatasetLineage).where(
            DatasetLineage.tenant_id == tenant_id,
            DatasetLineage.downstream_resource_id == resource_id,
        )
        result = await session.execute(stmt)
        lineage_rows = result.scalars().all()

        for lineage in lineage_rows:
            upstream_id = lineage.upstream_resource_id

            # Recursively crawl upstream
            await crawl(upstream_id, depth + 1)

            # Add edge from upstream to this node
            if upstream_id in visited:
                graph.add_edge(upstream_id, resource_id)

    # Start crawling from root
    await crawl(root_id)

    return graph
