"""Dataset Service - Bridge Resources to Data Execution.

This service implements the code_ref linkage pattern:
1. Load DatasetInstance Resource + Extension table
2. Load referenced Pipeline/Store/Accessor Instances
3. Load their Definitions to get code_ref values
4. Use FACTORY.build(code_ref, config) to instantiate execution objects
5. Execute and return data

Key Insight: The two-table pattern
- Resource table: governance (RBAC, versioning, activity)
- Extension table: domain data (code_ref, config, metrics)

Phase 2.8a: Instance creation now also creates Flow Execution Resources:
- When DatasetInstance is created, a Prefect deployment is also created
- The deployment ID is stored in DatasetInstance.prefect_deployment_id
- This deployment can be triggered to create PipelineRuns
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.core.rbac.models import ActorContext
from libs.data.registry import ACCESSOR_FACTORY, PIPELINE_FACTORY, STORE_FACTORY
from libs.db.models.quant import (
    AccessorDefinition,
    AccessorInstance,
    DatasetInstance,
    PipelineDefinition,
    PipelineInstance,
    StoreDefinition,
    StoreInstance,
)
from libs.db.models.resource import Resource

if TYPE_CHECKING:
    import pandas as pd

    from libs.orchestration import OrchestratorAdapter

from libs.orchestration import LineageResolver

logger = logging.getLogger(__name__)


class DatasetService:
    """Service for dataset operations with code_ref integration.

    This service demonstrates the bridge between:
    - Resource model (governance layer)
    - Factory-based execution (domain layer)

    The code_ref field links Definition Resources to factory-registered implementations.
    """

    def __init__(
        self,
        data_dir: Path | str | None = None,
        orchestrator: Optional["OrchestratorAdapter"] = None,
    ) -> None:
        """Initialize service.

        Args:
            data_dir: Base directory for data storage. Defaults to ./data/
            orchestrator: Optional orchestrator for creating Flow Execution Resources.
                         If not provided, deployments will not be created.
        """
        self.data_dir = Path(data_dir) if data_dir else Path("./data")
        self._orchestrator = orchestrator
        self._lineage_resolver = LineageResolver()

    async def get_dataset(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        dataset_id: UUID,
    ) -> dict[str, Any]:
        """Get dataset metadata and status.

        Args:
            session: Database session
            tenant_id: Tenant ID
            dataset_id: Dataset resource ID

        Returns:
            Dataset info including freshness status
        """
        # Load Resource
        resource = await session.get(Resource, dataset_id)
        if not resource or resource.tenant_id != tenant_id:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Load Extension
        instance = await session.get(DatasetInstance, dataset_id)
        if not instance:
            raise ValueError(f"DatasetInstance {dataset_id} not found")

        return {
            "id": str(resource.id),
            "name": resource.name,
            "type": resource.type,
            "status": resource.status,
            "freshness_status": instance.freshness_status,
            "last_data_date": str(instance.last_data_date)
            if instance.last_data_date
            else None,
            "last_refresh_at": instance.last_refresh_at.isoformat()
            if instance.last_refresh_at
            else None,
            "row_count": instance.row_count,
            "created_at": resource.created_at.isoformat(),
        }

    async def preview_dataset(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Preview dataset data with optional PIT filtering.

        This method demonstrates the full code_ref linkage:
        1. Load DatasetInstance and its component instances
        2. Load Definitions to get code_ref values
        3. Build execution objects from factories
        4. Execute accessor.get() to retrieve data

        Args:
            session: Database session
            actor: Actor context for RBAC
            dataset_id: Dataset resource ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            as_of_date: Point-in-time date (what was known as of this date)
            limit: Maximum rows to return

        Returns:
            Preview data as dict with columns, data, and metadata
        """
        # 1. Load DatasetInstance
        instance = await session.get(DatasetInstance, dataset_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"DatasetInstance {dataset_id} not found")

        # 2. Load component instances
        store_inst = await session.get(StoreInstance, instance.store_instance_id)
        accessor_inst = await session.get(
            AccessorInstance, instance.accessor_instance_id
        )

        if not store_inst or not accessor_inst:
            raise ValueError("Dataset component instances not found")

        # 3. Load definitions to get code_ref
        store_def = await session.get(
            StoreDefinition, store_inst.definition_resource_id
        )
        accessor_def = await session.get(
            AccessorDefinition, accessor_inst.definition_resource_id
        )

        if not store_def or not accessor_def:
            raise ValueError("Dataset component definitions not found")

        # 4. Build execution objects using code_ref
        store = STORE_FACTORY.build(
            store_def.code_ref,  # e.g., "ParquetStore"
            resource_id=str(store_inst.resource_id),
            config=store_inst.config_json or {},
            data_dir=self.data_dir,
        )

        accessor = ACCESSOR_FACTORY.build(
            accessor_def.code_ref,  # e.g., "PITAccessor"
            resource_id=str(accessor_inst.resource_id),
            config=accessor_inst.config_json or {},
            store=store,
        )

        # 5. Execute
        df = accessor.get(
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
        )

        # Limit rows
        if len(df) > limit:
            df = df.head(limit)

        # Convert to response format
        return self._dataframe_to_response(df, instance)

    async def refresh_dataset(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
    ) -> dict[str, Any]:
        """Trigger dataset refresh.

        Args:
            session: Database session
            actor: Actor context
            dataset_id: Dataset resource ID

        Returns:
            Refresh status
        """
        # Load instance
        instance = await session.get(DatasetInstance, dataset_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"DatasetInstance {dataset_id} not found")

        # Load pipeline instance and definition
        pipeline_inst = await session.get(
            PipelineInstance, instance.pipeline_instance_id
        )
        if not pipeline_inst:
            raise ValueError("Pipeline instance not found")

        pipeline_def = await session.get(
            PipelineDefinition, pipeline_inst.definition_resource_id
        )
        if not pipeline_def:
            raise ValueError("Pipeline definition not found")

        # Build pipeline
        _pipeline = PIPELINE_FACTORY.build(
            pipeline_def.code_ref,  # e.g., "ExpressionPipeline"
            resource_id=str(pipeline_inst.resource_id),
            config=pipeline_inst.config_json or {},
        )

        # Load resource for activity
        resource = await session.get(Resource, dataset_id)

        # Emit activity for refresh start
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=dataset_id,
            resource_type=resource.type if resource else "DatasetInstance",
            action="dataset.refresh_started",
            payload={"pipeline": pipeline_def.code_ref},
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        # Execute pipeline (this would typically be async/queued)
        # For now, we just return the pending status
        return {
            "dataset_id": str(dataset_id),
            "status": "refresh_queued",
            "pipeline": pipeline_def.code_ref,
        }

    async def create_dataset(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        parent_id: UUID,
        pipeline_instance_id: UUID,
        store_instance_id: UUID,
        accessor_instance_id: UUID,
        freshness_status: str = "unknown",
        schedule: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a new dataset instance with Flow Execution Resource.

        A DatasetInstance is a high-level resource that combines:
        - A PipelineInstance (data source/transformation)
        - A StoreInstance (where data is stored)
        - An AccessorInstance (how data is retrieved)

        Phase 2.8a: Instance creation also creates a Flow Execution Resource:
        - Creates a Prefect deployment for the dataset refresh flow
        - Stores the deployment ID in DatasetInstance.prefect_deployment_id
        - The deployment can be triggered to create PipelineRuns

        Args:
            session: Database session
            actor: Actor context for RBAC
            name: Dataset name
            parent_id: Parent resource ID (typically a Project)
            pipeline_instance_id: Reference to pipeline instance
            store_instance_id: Reference to store instance
            accessor_instance_id: Reference to accessor instance
            freshness_status: Initial freshness status
            schedule: Optional schedule configuration (cron, interval)

        Returns:
            Created dataset info including deployment_id
        """
        from uuid import uuid4

        # Verify component instances exist and belong to tenant
        pipeline_inst = await session.get(PipelineInstance, pipeline_instance_id)
        if not pipeline_inst or pipeline_inst.tenant_id != actor.tenant_id:
            raise ValueError(f"PipelineInstance {pipeline_instance_id} not found")

        store_inst = await session.get(StoreInstance, store_instance_id)
        if not store_inst or store_inst.tenant_id != actor.tenant_id:
            raise ValueError(f"StoreInstance {store_instance_id} not found")

        accessor_inst = await session.get(AccessorInstance, accessor_instance_id)
        if not accessor_inst or accessor_inst.tenant_id != actor.tenant_id:
            raise ValueError(f"AccessorInstance {accessor_instance_id} not found")

        # Create Resource
        resource_id = uuid4()
        resource = Resource(
            id=resource_id,
            tenant_id=actor.tenant_id,
            type="DatasetInstance",
            parent_id=parent_id,
            name=name,
            status="active",
            created_by=actor.id,
        )
        session.add(resource)

        # Create DatasetInstance extension
        instance = DatasetInstance(
            resource_id=resource_id,
            tenant_id=actor.tenant_id,
            pipeline_instance_id=pipeline_instance_id,
            store_instance_id=store_instance_id,
            accessor_instance_id=accessor_instance_id,
            freshness_status=freshness_status,
            row_count=0,
        )
        session.add(instance)

        # Flush to ensure instance is persisted before creating lineage
        await session.flush()

        # Phase 2.8.1: Build lineage DAG and create subscriptions
        upstream_ids: list[str] = []
        try:
            dag = await self._lineage_resolver.build_dag_for_instance(
                session, resource_id, actor.tenant_id
            )
            if dag.has_dependencies:
                # Store upstream IDs on instance for fast execution checks
                instance.upstream_resource_ids = [str(uid) for uid in dag.upstream_ids]
                # Initialize upstream status (all unknown until first run)
                instance.upstream_status = {
                    str(uid): "unknown" for uid in dag.upstream_ids
                }
                # Create lineage records and subscriptions for pub/sub
                await self._lineage_resolver.create_lineage_and_subscriptions(
                    session, dag
                )
                upstream_ids = [str(uid) for uid in dag.upstream_ids]
                logger.info(
                    f"Created lineage for {resource_id} with {len(dag.upstream_ids)} upstreams"
                )
        except Exception as e:
            # Log but don't fail - lineage can be created later
            logger.warning(f"Failed to create lineage for {resource_id}: {e}")

        # Phase 2.8a: Create Flow Execution Resource (Prefect deployment)
        deployment_id = None
        if self._orchestrator:
            try:
                deployment_result = await self._orchestrator.create_deployment(
                    instance_id=resource_id,
                    flow_name=f"{name}_refresh",
                    flow_template="dataset_refresh",
                    parameters={
                        "dataset_id": str(resource_id),
                        "pipeline_instance_id": str(pipeline_instance_id),
                    },
                    schedule=schedule,
                    tags={
                        "tenant_id": str(actor.tenant_id),
                        "resource_type": "DatasetInstance",
                    },
                )
                deployment_id = deployment_result.deployment_id
                instance.prefect_deployment_id = deployment_id
                logger.info(
                    f"Created deployment {deployment_id} for dataset {resource_id}"
                )
            except Exception as e:
                # Log but don't fail - deployment can be created later
                logger.warning(f"Failed to create deployment for {resource_id}: {e}")

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type="DatasetInstance",
            action="dataset.created",
            payload={
                "name": name,
                "pipeline_instance_id": str(pipeline_instance_id),
                "store_instance_id": str(store_instance_id),
                "accessor_instance_id": str(accessor_instance_id),
                "deployment_id": deployment_id,
                "upstream_ids": upstream_ids,
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(resource_id),
            "name": name,
            "type": "DatasetInstance",
            "status": "active",
            "freshness_status": freshness_status,
            "pipeline_instance_id": str(pipeline_instance_id),
            "store_instance_id": str(store_instance_id),
            "accessor_instance_id": str(accessor_instance_id),
            "prefect_deployment_id": deployment_id,
            "upstream_resource_ids": upstream_ids,
        }

    async def list_datasets(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        parent_id: UUID | None = None,
        freshness_status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List datasets with optional filters.

        Args:
            session: Database session
            actor: Actor context
            parent_id: Filter by parent resource
            freshness_status: Filter by freshness (fresh, stale, unknown)
            limit: Maximum results

        Returns:
            List of dataset info dicts
        """
        # Build query
        stmt = (
            select(Resource, DatasetInstance)
            .join(DatasetInstance, Resource.id == DatasetInstance.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "DatasetInstance",
                Resource.status == "active",
            )
        )

        if parent_id:
            stmt = stmt.where(Resource.parent_id == parent_id)

        if freshness_status:
            stmt = stmt.where(DatasetInstance.freshness_status == freshness_status)

        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(resource.id),
                "name": resource.name,
                "freshness_status": instance.freshness_status,
                "last_data_date": str(instance.last_data_date)
                if instance.last_data_date
                else None,
                "row_count": instance.row_count,
            }
            for resource, instance in rows
        ]

    def _dataframe_to_response(
        self,
        df: "pd.DataFrame",
        instance: DatasetInstance,
    ) -> dict[str, Any]:
        """Convert DataFrame to API response format.

        Args:
            df: DataFrame to convert
            instance: DatasetInstance for metadata

        Returns:
            Response dict with columns, data, metadata
        """
        import pandas as pd

        # Handle index
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            df.columns = ["date"] + list(df.columns[1:])

        # Convert to records
        records = df.to_dict(orient="records")

        # Convert dates/timestamps to strings
        for record in records:
            for key, value in record.items():
                if isinstance(value, (pd.Timestamp, date)):
                    record[key] = str(value)

        return {
            "columns": list(df.columns),
            "data": records,
            "row_count": len(records),
            "total_rows": instance.row_count,
            "freshness_status": instance.freshness_status,
        }

    async def get_lineage_dag(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
        *,
        direction: str = "both",
        depth: int = 3,
    ) -> dict[str, Any]:
        """Get lineage DAG for visualization.

        Returns a DAG structure suitable for graph visualization libraries.

        Args:
            session: Database session
            actor: Actor context for RBAC
            dataset_id: Dataset resource ID
            direction: "upstream", "downstream", or "both"
            depth: Maximum traversal depth (1-10)

        Returns:
            DAG dict with nodes, edges, execution_order, freshness
        """
        # Get the basic graph from LineageResolver
        graph = await self._lineage_resolver.get_lineage_graph(
            session, dataset_id, direction=direction, max_depth=depth
        )

        # Enhance nodes with status
        for node in graph["nodes"]:
            node_id = UUID(node["id"])
            instance = await session.get(DatasetInstance, node_id)
            if instance:
                node["status"] = instance.freshness_status
            else:
                node["status"] = "unknown"

        # Get execution order
        execution_order: list[list[str]] = []
        try:
            batches = await self._lineage_resolver.get_execution_order(
                session, dataset_id
            )
            execution_order = [[str(uid) for uid in batch] for batch in batches]
        except ValueError:
            # Cycle detected or other issue
            pass

        # Get freshness status
        freshness = None
        try:
            from libs.orchestration import FreshnessChecker, StatusStore

            status_store = StatusStore(session)
            freshness_checker = FreshnessChecker(status_store)
            report = await self._lineage_resolver.check_upstream_freshness(
                session, dataset_id, freshness_checker
            )
            freshness = {
                "all_ready": report.all_ready,
                "blockers": [
                    {"id": str(uid), "status": str(report.status_map.get(uid))}
                    for uid in report.blocking_resources
                ],
            }
        except Exception:
            # Freshness check failed - non-critical
            pass

        return {
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "center_id": graph["center_id"],
            "execution_order": execution_order,
            "freshness": freshness,
        }

    # =========================================================================
    # Schedule Management (Phase 2.8.5)
    # =========================================================================

    async def get_schedule(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
    ) -> dict[str, Any]:
        """Get schedule configuration for a dataset.

        Args:
            session: Database session
            actor: Actor context
            dataset_id: Dataset resource ID

        Returns:
            Schedule info including deployment status
        """
        # Load resource and extension
        resource = await session.get(Resource, dataset_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Dataset {dataset_id} not found")

        instance = await session.get(DatasetInstance, dataset_id)
        if not instance:
            raise ValueError(f"Dataset instance {dataset_id} not found")

        # Get schedule config from instance
        schedule_config = instance.config.get("schedule", {}) if instance.config else {}

        # Get deployment status from orchestrator if available
        deployment_info = None
        if self._orchestrator and instance.prefect_deployment_id:
            try:
                deployment_info = await self._orchestrator.get_deployment(
                    instance.prefect_deployment_id
                )
            except Exception:
                pass

        return {
            "id": str(dataset_id),
            "name": resource.name,
            "schedule": {
                "cron": schedule_config.get("cron"),
                "interval_seconds": schedule_config.get("interval_seconds"),
                "active": schedule_config.get("active", True),
                "last_scheduled_at": None,  # Could be enriched from orchestrator
                "next_scheduled_at": None,  # Could be enriched from orchestrator
            }
            if schedule_config
            else None,
            "deployment_id": instance.prefect_deployment_id,
            "orchestrator_kind": deployment_info.get("kind")
            if deployment_info
            else None,
        }

    async def update_schedule(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
        schedule: dict[str, Any],
    ) -> dict[str, Any]:
        """Update schedule configuration for a dataset.

        This updates the schedule in the DatasetInstance config and
        syncs it to the orchestrator (Prefect deployment).

        Args:
            session: Database session
            actor: Actor context
            dataset_id: Dataset resource ID
            schedule: Schedule config with cron/interval_seconds/active

        Returns:
            Updated schedule info
        """
        # Load resource and extension
        resource = await session.get(Resource, dataset_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Dataset {dataset_id} not found")

        instance = await session.get(DatasetInstance, dataset_id)
        if not instance:
            raise ValueError(f"Dataset instance {dataset_id} not found")

        # Validate schedule config
        if schedule.get("cron") and schedule.get("interval_seconds"):
            raise ValueError("Cannot specify both cron and interval_seconds")

        # Update config
        config = instance.config or {}
        config["schedule"] = {
            "cron": schedule.get("cron"),
            "interval_seconds": schedule.get("interval_seconds"),
            "active": schedule.get("active", True),
        }
        instance.config = config

        # Sync to orchestrator if available
        sync_success = False
        if self._orchestrator and instance.prefect_deployment_id:
            try:
                sync_success = await self._orchestrator.update_schedule(
                    deployment_id=instance.prefect_deployment_id,
                    schedule={
                        "cron": schedule.get("cron"),
                        "interval_seconds": schedule.get("interval_seconds"),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to sync schedule to orchestrator: {e}")

        # Record activity
        await record_activity_with_outbox(
            session,
            ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_id=actor.principal_id,
                resource_id=dataset_id,
                action="schedule.updated",
                payload={
                    "schedule": config["schedule"],
                    "synced_to_orchestrator": sync_success,
                },
            ),
        )

        await session.commit()

        return {
            "id": str(dataset_id),
            "name": resource.name,
            "schedule": config["schedule"],
            "deployment_id": instance.prefect_deployment_id,
            "orchestrator_kind": "prefect" if instance.prefect_deployment_id else None,
        }

    async def delete_schedule(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
    ) -> dict[str, Any]:
        """Remove schedule from a dataset.

        Disables the schedule but keeps the deployment for manual triggers.

        Args:
            session: Database session
            actor: Actor context
            dataset_id: Dataset resource ID

        Returns:
            Updated schedule info
        """
        # Load resource and extension
        resource = await session.get(Resource, dataset_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Dataset {dataset_id} not found")

        instance = await session.get(DatasetInstance, dataset_id)
        if not instance:
            raise ValueError(f"Dataset instance {dataset_id} not found")

        # Clear schedule from config
        config = instance.config or {}
        config.pop("schedule", None)
        instance.config = config

        # Disable schedule in orchestrator (keep deployment for manual triggers)
        if self._orchestrator and instance.prefect_deployment_id:
            try:
                await self._orchestrator.update_schedule(
                    deployment_id=instance.prefect_deployment_id,
                    schedule={},  # Empty schedule = no schedule
                )
            except Exception as e:
                logger.warning(f"Failed to disable schedule in orchestrator: {e}")

        # Record activity
        await record_activity_with_outbox(
            session,
            ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_id=actor.principal_id,
                resource_id=dataset_id,
                action="schedule.deleted",
                payload={},
            ),
        )

        await session.commit()

        return {
            "id": str(dataset_id),
            "name": resource.name,
            "schedule": None,
            "deployment_id": instance.prefect_deployment_id,
            "orchestrator_kind": None,
        }
