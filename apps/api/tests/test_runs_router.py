"""Integration tests for Runs API router.

Verifies:
- Full integration with real Service, DB, and LocalOrchestrator
- Correct dependency injection override for DB session
"""

import pytest
from uuid import uuid4
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from apps.api.deps import get_db
from libs.db.models.resource import Resource
from libs.db.models.quant import DatasetInstance, ExperimentInstance
from libs.db.models.identity import Tenant, Principal

# --- Fixtures ---


@pytest.fixture
async def auth_headers(db_session):
    """Create a tenant and principal, return auth headers."""
    # Patch commit to flush GLOBALLY for this test file's session usage
    # to prevent closing the transaction in fixtures or service calls.
    db_session.commit = db_session.flush

    tenant_id = uuid4()
    principal_id = uuid4()

    # Create Tenant
    tenant = Tenant(id=tenant_id, name=f"TestTenant-{tenant_id}")
    db_session.add(tenant)

    # Create Principal
    principal = Principal(
        id=principal_id,
        tenant_id=tenant_id,
        kind="user",
        display_name="Tester",
        email=f"test-{principal_id}@example.com",
        status="active",
    )
    db_session.add(principal)
    await db_session.commit()

    return {"X-Principal-Id": str(principal_id), "X-Tenant-Id": str(tenant_id)}


@pytest.mark.asyncio
async def test_submit_pipeline_run_integration(db_session, auth_headers):
    """Test POST /runs/pipelines with real services."""

    # Override get_db to use test fixture session (transaction scope)
    # Patch commit to flush to keep transaction open for rollback
    db_session.commit = db_session.flush
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        # 1. Setup Data
        from uuid import UUID
        from libs.db.models.rbac import RoleBinding, RolePermission
        from libs.core.rbac.models import Permission

        tenant_id = UUID(auth_headers["X-Tenant-Id"])
        owner_id = UUID(auth_headers["X-Principal-Id"])
        dataset_id = uuid4()

        # Dataset components (dummy resources to satisfy FKs)
        pipeline_id = uuid4()
        store_id = uuid4()
        accessor_id = uuid4()

        db_session.add(
            Resource(
                id=pipeline_id,
                tenant_id=tenant_id,
                owner_principal_id=owner_id,
                type="PipelineInstance",
                name="P",
            )
        )
        db_session.add(
            Resource(
                id=store_id,
                tenant_id=tenant_id,
                owner_principal_id=owner_id,
                type="StoreInstance",
                name="S",
            )
        )
        db_session.add(
            Resource(
                id=accessor_id,
                tenant_id=tenant_id,
                owner_principal_id=owner_id,
                type="AccessorInstance",
                name="A",
            )
        )

        # Resource & Dataset
        resource = Resource(
            id=dataset_id,
            tenant_id=tenant_id,
            owner_principal_id=owner_id,
            name="Real Dataset",
            type="DatasetInstance",
        )
        db_session.add(resource)

        dataset = DatasetInstance(
            resource_id=dataset_id,
            tenant_id=tenant_id,
            freshness_status="unknown",
            pipeline_instance_id=pipeline_id,
            store_instance_id=store_id,
            accessor_instance_id=accessor_id,
        )
        db_session.add(dataset)

        # RBAC Setup
        role_name = f"test-role-{uuid4()}"
        # Permit Update
        db_session.add(
            RolePermission(
                tenant_id=tenant_id,
                resource_type="DatasetInstance",
                role_name=role_name,
                perm_name=Permission.RESOURCE_UPDATE.value,
            )
        )
        # Bind Role
        db_session.add(
            RoleBinding(
                tenant_id=tenant_id,
                principal_id=owner_id,
                scope_resource_id=dataset_id,
                role_name=role_name,
                granted_by=owner_id,
            )
        )
        await db_session.commit()

        # 2. Execute Request
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            payload = {
                "dataset_id": str(dataset_id),
                "mode": "incremental",
                "force": True,
            }

            resp = await client.post(
                "/runs/pipelines", json=payload, headers=auth_headers
            )

            # 3. Verify
            assert resp.status_code == 201
            data = resp.json()
            assert data["dataset_id"] == str(dataset_id)
            assert data["status"] == "running"  # Local orchestrator default
            assert data["orchestrator_kind"] == "local"

    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_submit_experiment_run_integration(db_session, auth_headers):
    """Test POST /runs/experiments with real services."""

    app.dependency_overrides[get_db] = lambda: db_session

    try:
        # 1. Setup Data
        from uuid import UUID
        from libs.db.models.rbac import RoleBinding, RolePermission
        from libs.core.rbac.models import Permission

        tenant_id = UUID(auth_headers["X-Tenant-Id"])
        owner_id = UUID(auth_headers["X-Principal-Id"])
        experiment_id = uuid4()

        resource = Resource(
            id=experiment_id,
            tenant_id=tenant_id,
            owner_principal_id=owner_id,
            name="Real Experiment",
            type="ExperimentInstance",
        )
        db_session.add(resource)

        experiment = ExperimentInstance(
            resource_id=experiment_id,
            tenant_id=tenant_id,
            expression_text="MEAN($price)",
            input_datasets_json={},
        )
        db_session.add(experiment)

        # RBAC Setup
        role_name = f"test-role-{uuid4()}"
        # Permit Read
        db_session.add(
            RolePermission(
                tenant_id=tenant_id,
                resource_type="ExperimentInstance",
                role_name=role_name,
                perm_name=Permission.RESOURCE_READ.value,
            )
        )
        # Bind Role
        db_session.add(
            RoleBinding(
                tenant_id=tenant_id,
                principal_id=owner_id,
                scope_resource_id=experiment_id,
                role_name=role_name,
                granted_by=owner_id,
            )
        )
        await db_session.commit()

        # 2. Execute Request
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            payload = {"experiment_id": str(experiment_id), "limit": 10}

            resp = await client.post(
                "/runs/experiments", json=payload, headers=auth_headers
            )

            # 3. Verify
            assert resp.status_code == 201
            data = resp.json()
            assert data["experiment_id"] == str(experiment_id)
            assert data["orchestrator_run_id"]

    finally:
        app.dependency_overrides = {}
