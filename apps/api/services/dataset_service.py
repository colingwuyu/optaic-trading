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
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
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


class DatasetService:
    """Service for dataset operations with code_ref integration.

    This service demonstrates the bridge between:
    - Resource model (governance layer)
    - Factory-based execution (domain layer)

    The code_ref field links Definition Resources to factory-registered implementations.
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        """Initialize service.

        Args:
            data_dir: Base directory for data storage. Defaults to ./data/
        """
        self.data_dir = Path(data_dir) if data_dir else Path("./data")

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
    ) -> dict[str, Any]:
        """Create a new dataset instance.

        A DatasetInstance is a high-level resource that combines:
        - A PipelineInstance (data source/transformation)
        - A StoreInstance (where data is stored)
        - An AccessorInstance (how data is retrieved)

        Args:
            session: Database session
            actor: Actor context for RBAC
            name: Dataset name
            parent_id: Parent resource ID (typically a Project)
            pipeline_instance_id: Reference to pipeline instance
            store_instance_id: Reference to store instance
            accessor_instance_id: Reference to accessor instance
            freshness_status: Initial freshness status

        Returns:
            Created dataset info
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
