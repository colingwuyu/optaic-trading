"""Integration tests for DatasetService.

Verifies the "Bridge" pattern:
Resource (Governance) -> Extension (Domain) -> Factory (Execution)
"""

import pytest
from uuid import uuid4
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import ActorContext
from libs.db.models.resource import Resource
from libs.db.models.quant import (
    DatasetInstance,
    PipelineDefinition,
    PipelineInstance,
    StoreDefinition,
    StoreInstance,
    AccessorDefinition,
    AccessorInstance,
)
from apps.api.services.dataset_service import DatasetService


@pytest.fixture
def actor():
    return ActorContext(id=uuid4(), tenant_id=uuid4(), kind="user")


async def create_definition(
    session: AsyncSession,
    tenant_id,
    principal_id,
    model_cls,
    name: str,
    code_ref: str,
    interface_spec: str = "optaic.interfaces.Base",
    **kwargs,
):
    """Helper to create a Definition Resource + Extension."""
    resource_id = uuid4()

    # Create Resource
    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type=model_cls.__name__,
        name=name,
        status="active",
    )
    session.add(resource)

    # Create Extension
    def_extension = model_cls(
        resource_id=resource_id,
        tenant_id=tenant_id,
        code_ref=code_ref,
        interface_spec=interface_spec,
        **kwargs,
    )
    session.add(def_extension)
    await session.flush()
    return def_extension


async def create_instance(
    session: AsyncSession,
    tenant_id,
    principal_id,
    model_cls,
    definition_id,
    name: str,
    config: dict = None,
):
    """Helper to create an Instance Resource + Extension."""
    resource_id = uuid4()

    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type=model_cls.__name__,
        name=name,
        status="active",
    )
    session.add(resource)

    inst_extension = model_cls(
        resource_id=resource_id,
        tenant_id=tenant_id,
        definition_resource_id=definition_id,
        config_json=config or {},
    )
    session.add(inst_extension)
    await session.flush()
    return inst_extension


@pytest.mark.asyncio
class TestDatasetServiceIntegration:
    """Test full integration of DatasetService with Factories."""

    async def test_preview_dataset_integration(
        self, db_session: AsyncSession, actor: ActorContext, tmp_path
    ):
        """
        Verify that preview_dataset loads components, resolves code_refs,
        builds objects via factories, and returns data.
        """
        # Patch commit to flush (standard test pattern)
        db_session.commit = db_session.flush

        # 1. Setup Definitions (Validation that factories have these code_refs)
        # Using ExpressionPipeline, VirtualStore, SimpleAccessor as they describe self-contained logic
        pipeline_def = await create_definition(
            db_session,
            actor.tenant_id,
            actor.id,
            PipelineDefinition,
            "Test Pipeline Def",
            "ExpressionPipeline",
            category="expression",
        )

        store_def = await create_definition(
            db_session,
            actor.tenant_id,
            actor.id,
            StoreDefinition,
            "Test Store Def",
            "VirtualStore",
            backend_type="virtual",
        )

        accessor_def = await create_definition(
            db_session,
            actor.tenant_id,
            actor.id,
            AccessorDefinition,
            "Test Accessor Def",
            "SimpleAccessor",
            accessor_type="simple",
        )

        # 2. Setup Instances

        # Pipeline: Simple expression "A * 2"
        # Since it's an ExpressionPipeline, we need to provide input data context or use a simple constant/generator
        # For simplicity, let's use a pure generation expression if supported, or prepopulate the store.
        # But wait, ExpressionPipeline usually Reads from store or other datasets.
        # Actually, let's use the Store to Pre-Populate data, and use SimpleAccessor to read it.
        # We don't necessarily need to RUN the pipeline here, just PREVIEW the dataset (which reads from Store via Accessor).
        # DatasetService.preview_dataset uses Accessor -> Store. It does NOT run the pipeline.

        pipeline_inst = await create_instance(
            db_session,
            actor.tenant_id,
            actor.id,
            PipelineInstance,
            pipeline_def.resource_id,
            "Test Pipeline Inst",
            config={"expression": "1"},  # Config required but not used for preview
        )

        # Configure Store to use a specific subdir in tmp_path so we can write real files
        # VirtualStore uses 'data_dir' passed from service + resource_id
        store_inst = await create_instance(
            db_session,
            actor.tenant_id,
            actor.id,
            StoreInstance,
            store_def.resource_id,
            "Test Store Inst",
            config={},
        )

        accessor_inst = await create_instance(
            db_session,
            actor.tenant_id,
            actor.id,
            AccessorInstance,
            accessor_def.resource_id,
            "Test Accessor Inst",
            config={},
        )

        # 3. Create DatasetInstance
        dataset_resource_id = uuid4()
        dataset_res = Resource(
            id=dataset_resource_id,
            tenant_id=actor.tenant_id,
            owner_principal_id=actor.id,
            type="DatasetInstance",
            name="Integration Dataset",
            status="active",
        )
        db_session.add(dataset_res)

        dataset_inst = DatasetInstance(
            resource_id=dataset_resource_id,
            tenant_id=actor.tenant_id,
            pipeline_instance_id=pipeline_inst.resource_id,
            store_instance_id=store_inst.resource_id,
            accessor_instance_id=accessor_inst.resource_id,
            freshness_status="fresh",
            row_count=0,
        )
        db_session.add(dataset_inst)
        await db_session.flush()

        # 4. Pre-populate Data in the Store
        # We need to manually instantiate the store to write data to it,
        # mimicking a prior pipeline run.
        from libs.data.registry import STORE_FACTORY
        from pandas import DataFrame

        # The service uses self.data_dir. We must match it.
        service = DatasetService(data_dir=tmp_path)

        # Build store manually to write
        store = STORE_FACTORY.build(
            "VirtualStore",
            resource_id=str(store_inst.resource_id),
            config={},
            data_dir=tmp_path,
        )

        test_df = DataFrame({"col_a": [1, 2, 3], "col_b": ["x", "y", "z"]})
        store.write(test_df)

        # Update row count
        dataset_inst.row_count = 3
        dataset_inst.last_data_date = date.today()
        await db_session.flush()

        # 5. Execute Test: Preview
        result = await service.preview_dataset(
            session=db_session, actor=actor, dataset_id=dataset_resource_id, limit=10
        )

        # 6. Verify
        assert result["freshness_status"] == "fresh"
        assert result["total_rows"] == 3
        assert result["columns"] == ["col_a", "col_b"]
        assert len(result["data"]) == 3
        assert result["data"][0]["col_a"] == 1
        assert result["data"][1]["col_b"] == "y"
