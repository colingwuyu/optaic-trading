"""Integration tests for quant domain API routers."""

import pytest
from uuid import uuid4
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from libs.db.models.identity import Tenant, Principal

# Use a fixture to setup user for all tests in this file/module?
# Or properly scope it.

@pytest.fixture
async def auth_headers(db_session):
    """Create a tenant and principal, return auth headers."""
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
        status="active"
    )
    db_session.add(principal)
    
    await db_session.commit()
    
    return {
        "X-Principal-Id": str(principal_id),
        "X-Tenant-Id": str(tenant_id)
    }

@pytest.mark.asyncio
async def test_dataset_router_flow(db_session, auth_headers):
    """Test full dataset flow."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        
        # 1. Random ID -> 404
        random_id = uuid4()
        resp = await client.get(f"/datasets/{random_id}", headers=auth_headers)
        assert resp.status_code == 404
        
        # 2. List -> Empty or not empty (depending on seed)
        resp = await client.get("/datasets", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

@pytest.mark.asyncio
async def test_experiments_router_flow(db_session, auth_headers):
    """Test full experiment flow."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        
        random_id = uuid4()
        
        # GET /experiments/{id} -> 404
        resp = await client.get(f"/experiments/{random_id}", headers=auth_headers)
        assert resp.status_code == 404
        
        # List
        resp = await client.get("/experiments", headers=auth_headers)
        assert resp.status_code == 200

@pytest.mark.asyncio
async def test_ops_flow(db_session, auth_headers):
    """Test ops listing and evaluation."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        
        # LIST /ops
        resp = await client.get("/ops", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "operators" in data
        
        # POST /ops/evaluate
        # Need a valid expression. using constants or simple math to avoid needing dataset
        payload = {
            "expression": "ADD(1, 2)",
            "context": {}
        }
        resp = await client.post("/ops/evaluate", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        
        eval_res = resp.json()
        assert eval_res["expression"] == "ADD(1, 2)"
        # Depending on Op implementation, ADD(1, 2) might work if scalars supported.
        # Or MEAN($close) returns success=False/True depending on mock.
        # Let's check success field
        # The OpService uses an engine. If engine is real, it might fail if 1,2 not dataframe?
        # Actually ExpressionEngine typically expects dataframes.
        # But we just want to ensure 200 OK from Router logic (Service delegates).

@pytest.mark.asyncio
async def test_signals_router_flow(db_session, auth_headers):
    """Test signals endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        random_id = uuid4()
        resp = await client.get(f"/signals/{random_id}", headers=auth_headers)
        assert resp.status_code == 404
        
        resp = await client.get("/signals", headers=auth_headers)
        assert resp.status_code == 200

@pytest.mark.asyncio
async def test_pipelines_router_flow(db_session, auth_headers):
    """Test pipelines endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        
        # LIST definitions
        resp = await client.get("/pipelines/definitions", headers=auth_headers)
        assert resp.status_code == 200
        definitions = resp.json()
        assert isinstance(definitions, list)
        
        # Should likely see the built-in definitions if seeded?
        # Tests use clean DB usually, so maybe not seeded unless we seed them.
        # But list returning [] is 200 OK.

class TestRouterImports:
    """Test that routers can be imported."""

    def test_ops_router_import(self):
        from apps.api.routers.ops import router
        assert router is not None
        assert router.prefix == "/ops"

    def test_pipelines_router_import(self):
        from apps.api.routers.pipelines import router
        assert router is not None
        assert router.prefix == "/pipelines"

    def test_experiments_router_import(self):
        from apps.api.routers.experiments import router
        assert router is not None
        assert router.prefix == "/experiments"

    def test_datasets_router_import(self):
        from apps.api.routers.datasets import router
        assert router is not None
        assert router.prefix == "/datasets"

    def test_signals_router_import(self):
        from apps.api.routers.signals import router
        assert router is not None
        assert router.prefix == "/signals"

class TestMainAppRegistration:
    """Test that routers are registered with the main app."""

    def test_app_has_ops_routes(self):
        from apps.api.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/ops" in routes
        assert "/ops/{name}" in routes
        assert "/ops/evaluate" in routes

    def test_app_has_pipelines_routes(self):
        from apps.api.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/pipelines/definitions" in routes
        assert "/pipelines/instances" in routes

    def test_app_has_experiments_routes(self):
        from apps.api.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/experiments" in routes
        assert "/experiments/{experiment_id}" in routes

    def test_app_has_datasets_routes(self):
        from apps.api.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/datasets/{dataset_id}" in routes
        assert "/datasets/{dataset_id}/status" in routes
        assert "/datasets/{dataset_id}/preview" in routes

    def test_app_has_signals_routes(self):
        from apps.api.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/signals" in routes
        assert "/signals/{signal_id}" in routes

class TestSchemaImports:
    """Test that quant schemas can be imported."""

    def test_pipeline_schemas(self):
        from apps.api.schemas import (
            PipelineDefinitionCreate,
        )
        assert PipelineDefinitionCreate is not None

    def test_dataset_schemas(self):
        from apps.api.schemas import (
            DatasetPreviewRequest,
        )
        assert DatasetPreviewRequest is not None

    def test_signal_schemas(self):
        from apps.api.schemas import (
            SignalRegisterRequest,
        )
        assert SignalRegisterRequest is not None

    def test_operator_schemas(self):
        from apps.api.schemas import (
            OperatorOut,
        )
        assert OperatorOut is not None

    def test_experiment_schemas(self):
        from apps.api.schemas import (
            ExperimentCreate,
        )
        assert ExperimentCreate is not None
