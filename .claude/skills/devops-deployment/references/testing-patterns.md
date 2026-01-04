# Testing Patterns for OptAIC

This document defines how to write and run tests in the OptAIC project. **All tests must work without Docker or external services.**

## Testing Philosophy

### CRITICAL: NO MOCKS POLICY

**Mocks are NOT ALLOWED for internal application logic.** This is a non-negotiable requirement.

| Rule | Rationale |
|------|-----------|
| **NO AsyncMock** | Hides real async behavior, concurrency bugs |
| **NO MagicMock** | Creates false positives, doesn't test real code |
| **NO patch()** | Bypasses actual implementations |
| **NO mock databases** | Use real SQLite via `db_session` fixture |
| **NO mock orchestrators** | Use `LocalOrchestrator` with test executors |
| **NO mock services** | Instantiate real service classes |

**Why?** Mocks are "cheating" - they let tests pass without verifying the actual implementation. If you mock everything, you're testing mock behavior, not your code.

### What Tests MUST Do

1. **Use real database sessions** - `db_session` fixture from root `conftest.py`
2. **Create actual database records** - SQL inserts, not mock objects
3. **Use real service classes** - Instantiate and call real methods
4. **Use LocalOrchestrator** - With custom node executors for fast execution
5. **Verify KEY CONCEPTS** - Business logic, not just field existence
6. **Cover corner cases** - Edge conditions, failure modes, boundary values

### Acceptable Exceptions (External Third-Party Services Only)

Mocks are ONLY acceptable for true external third-party services that:
- Are outside our control (vendor APIs, external SaaS)
- Have rate limits or costs (payment processors, cloud APIs)
- Are unavailable in test environments (production-only services)

```python
# ACCEPTABLE: Mocking external vendor API
@patch("httpx.AsyncClient.get")
async def test_external_vendor_call(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {"vendor": "data"})
    # Test code that calls external vendor

# NOT ACCEPTABLE: Mocking internal services, database, orchestrator
```

### Test Categories

1. **Unit tests** - Test individual functions with real dependencies (SQLite, LocalOrchestrator)
2. **Integration tests** - Test full flows through API endpoints with sandbox infrastructure
3. **No Docker** - Tests must run on native Windows without containers

## Test Structure

```
libs/
├── core/tests/          # Pure Python, no DB
├── db/tests/            # SQLite fixtures, model tests
│   ├── conftest.py      # Shared fixtures
│   └── test_*.py        # Model-specific tests
└── sdk_py/tests/        # Client tests with httpx mocking

apps/
├── api/tests/           # FastAPI TestClient or live server
├── worker/tests/        # Message processing tests
└── agent/tests/         # Agent behavior tests

optaic/tests/            # CLI and runtime tests
```

## SQLite Test Fixtures

**DO NOT use PostgreSQL for tests.** Use the SQLite pattern:

```python
# libs/db/tests/conftest.py

import tempfile
from pathlib import Path
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

@pytest.fixture(scope="function")
def temp_db_path():
    """Fresh SQLite file per test function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.sqlite"

@pytest_asyncio.fixture(scope="function")
async def async_engine(temp_db_path):
    """Async SQLite engine for tests."""
    url = f"sqlite+aiosqlite:///{temp_db_path.as_posix()}"
    engine = create_async_engine(url, echo=False)

    # Create tables directly (avoid importing problematic models)
    async with engine.begin() as conn:
        for table in tables_to_create:
            await conn.run_sync(table.create, checkfirst=True)

    yield engine
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(async_engine) -> AsyncSession:
    """Session with transaction isolation per test."""
    factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()
```

## Running Tests

```bash
# All tests
uv run pytest

# Specific package
uv run pytest libs/db/tests/ -v

# Single test file
uv run pytest libs/db/tests/test_quant_models.py

# Single test
uv run pytest libs/db/tests/test_quant_models.py::TestSignalSpec::test_create_signal_spec

# With coverage
uv run pytest --cov=libs --cov-report=html
```

## API Integration Tests

For API tests, use FastAPI's TestClient or a live server:

### Option 1: TestClient (preferred for unit-style API tests)

```python
# apps/api/tests/test_resources.py

from fastapi.testclient import TestClient
from apps.api.main import app

def test_create_resource():
    with TestClient(app) as client:
        response = client.post("/resources", json={
            "type": "Space",
            "name": "Test Space",
        })
        assert response.status_code == 201
```

### Option 2: Live Server (for integration tests)

```python
# apps/api/tests/test_live_integration.py

import pytest
import httpx

@pytest.fixture(scope="module")
def live_server():
    """Start optaic server for integration tests."""
    import subprocess
    import time

    proc = subprocess.Popen([
        "optaic", "server",
        "--port", "9999",
        "--no-worker",
        "--no-agent",
    ])
    time.sleep(3)  # Wait for startup

    yield "http://localhost:9999"

    proc.terminate()
    proc.wait()

def test_health_check(live_server):
    response = httpx.get(f"{live_server}/health")
    assert response.status_code == 200
```

## Testing Without Mocks

### Using LocalOrchestrator for Pipeline Tests

Instead of mocking the orchestrator, use `LocalOrchestrator` with custom node executors:

```python
import asyncio
from libs.orchestration import LocalOrchestrator

def create_test_orchestrator():
    """Create LocalOrchestrator with simple test node executor."""
    async def simple_node_executor(node_id, node_type, code_ref, config):
        await asyncio.sleep(0.01)  # Simulate work
        return {"status": "success", "rows_processed": 100, "last_data_date": "2025-01-01"}

    return LocalOrchestrator(max_workers=2, node_executor=simple_node_executor)

# Failing executor for error tests
def create_failing_orchestrator():
    async def failing_executor(node_id, node_type, code_ref, config):
        raise RuntimeError("Simulated pipeline failure")
    return LocalOrchestrator(max_workers=1, node_executor=failing_executor)

# Slow executor for timeout tests
def create_slow_orchestrator(delay: float = 5.0):
    async def slow_executor(node_id, node_type, code_ref, config):
        await asyncio.sleep(delay)
        return {"status": "success"}
    return LocalOrchestrator(max_workers=1, node_executor=slow_executor)
```

### Creating Real Database Records

Use helper functions to create actual database records:

```python
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import text

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

async def create_tenant_and_principal(db_session):
    """Create real tenant and principal for tests."""
    tenant_id = uuid4()
    principal_id = uuid4()

    await db_session.execute(
        text("""
            INSERT INTO tenants (id, name, created_at)
            VALUES (:id, :name, :created_at)
        """),
        {"id": str(tenant_id), "name": "Test Tenant", "created_at": utcnow_iso()},
    )
    await db_session.execute(
        text("""
            INSERT INTO principals (id, tenant_id, type, email, created_at)
            VALUES (:id, :tenant_id, :type, :email, :created_at)
        """),
        {
            "id": str(principal_id),
            "tenant_id": str(tenant_id),
            "type": "user",
            "email": "test@example.com",
            "created_at": utcnow_iso(),
        },
    )
    await db_session.flush()
    return tenant_id, principal_id
```

### Testing Service Classes with Real Dependencies

```python
@pytest.mark.asyncio
async def test_pipeline_run_service_submits_run(db_session):
    """Test PipelineRunService with real DB and orchestrator."""
    # Setup real test data
    tenant_id, principal_id = await create_tenant_and_principal(db_session)
    dataset_id = await create_dataset_instance(db_session, tenant_id, principal_id)

    # Create real service with real dependencies
    orchestrator = create_test_orchestrator()
    status_store = StatusStore(db_session)
    service = PipelineRunService(orchestrator=orchestrator, status_store=status_store)

    # Execute with real session
    result = await service.submit_run(
        session=db_session,
        dataset_instance_id=dataset_id,
        actor=ActorContext(id=principal_id, tenant_id=tenant_id),
    )

    # Verify real database state
    assert result.run_id is not None
    run = await db_session.get(PipelineRun, result.run_id)
    assert run.status in ("queued", "running")
```

### Only Mock External Third-Party APIs

```python
# ONLY acceptable mock usage: External vendor APIs
@patch("httpx.AsyncClient.get")
async def test_external_data_vendor(mock_get):
    """Mock only truly external services like Bloomberg, Reuters, etc."""
    mock_get.return_value = Mock(
        status_code=200,
        json=lambda: {"vendor": "external_data"}
    )
    # Test code that calls external vendor API
```

## Test Data Helpers

Create test data with helper functions, not mocks:

```python
# libs/db/tests/helpers.py

from datetime import datetime, timezone
import uuid
from sqlalchemy import text

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

async def create_test_resource(
    session,
    tenant_id: str,
    principal_id: str,
    resource_type: str,
    name: str,
) -> str:
    """Create a resource with all required fields."""
    resource_id = str(uuid.uuid4())
    await session.execute(
        text("""
            INSERT INTO resources (id, tenant_id, owner_principal_id, type, name, status, metadata, created_at, updated_at)
            VALUES (:id, :tenant_id, :owner_principal_id, :type, :name, :status, :metadata, :created_at, :updated_at)
        """),
        {
            "id": resource_id,
            "tenant_id": tenant_id,
            "owner_principal_id": principal_id,
            "type": resource_type,
            "name": name,
            "status": "active",
            "metadata": "{}",
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    return resource_id
```

## Common Test Patterns

### Testing SQLAlchemy Models

```python
@pytest.mark.asyncio
async def test_create_model(db_session, test_tenant, test_resource):
    """Test creating a model record."""
    await db_session.execute(
        text("""
            INSERT INTO my_table (resource_id, tenant_id, field1, created_at)
            VALUES (:resource_id, :tenant_id, :field1, :created_at)
            RETURNING resource_id
        """),
        {
            "resource_id": str(test_resource),
            "tenant_id": str(test_tenant),
            "field1": "value",
            "created_at": utcnow(),
        },
    )

    result = await db_session.execute(
        text("SELECT field1 FROM my_table WHERE resource_id = :id"),
        {"id": str(test_resource)},
    )
    row = result.fetchone()
    assert row[0] == "value"
```

### Testing Services

```python
@pytest.mark.asyncio
async def test_service_creates_resource(db_session, test_tenant, test_principal):
    """Test service layer with real DB."""
    service = ResourceService()

    result = await service.create(
        session=db_session,
        actor=test_principal,
        payload=CreateResourceDTO(name="Test", type="Space"),
    )

    assert result.id is not None
    assert result.name == "Test"
```

### Testing CLI Commands

```python
from typer.testing import CliRunner
from optaic.cli import app

runner = CliRunner()

def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "optaic" in result.stdout.lower()

def test_doctor_command():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
```

## Test Quality Requirements

### Tests MUST Verify Key Concepts

Tests are not just for checking interfaces or field existence. They must verify:

| Aspect | What to Test |
|--------|--------------|
| **Business Logic** | Does the algorithm produce correct results? |
| **State Transitions** | Do status changes happen correctly? |
| **Edge Cases** | Empty inputs, null values, boundary conditions |
| **Error Handling** | Does failure produce correct error state? |
| **Concurrency** | Do parallel operations behave correctly? |
| **Data Integrity** | Are FK relationships maintained? |

### Test Design Principles

```python
class TestAutoTrigger:
    """Example of comprehensive test design."""

    async def test_auto_trigger_enabled_triggers_downstream(self, db_session):
        """Basic case: enabled auto-trigger fires."""
        # Setup: upstream completes, downstream has auto_trigger=True
        # Execute: mark upstream complete
        # Verify: downstream run was created

    async def test_auto_trigger_disabled_does_not_trigger(self, db_session):
        """Negative case: disabled auto-trigger does not fire."""
        # Setup: upstream completes, downstream has auto_trigger=False
        # Execute: mark upstream complete
        # Verify: NO downstream run created

    async def test_auto_trigger_chain_propagates(self, db_session):
        """Chain case: A -> B(auto) -> C(auto) all trigger."""
        # Setup: A -> B -> C chain, B and C have auto_trigger=True
        # Execute: complete A
        # Verify: B triggered, then C triggered

    async def test_auto_trigger_chain_stops_at_manual(self, db_session):
        """Edge case: chain stops when auto_trigger=False."""
        # Setup: A -> B(auto) -> C(manual)
        # Execute: complete A
        # Verify: B triggered, C NOT triggered

    async def test_diamond_pattern_waits_for_all_upstreams(self, db_session):
        """Complex case: diamond A -> (B,C) -> D waits for both."""
        # Setup: A -> B, A -> C, B -> D, C -> D
        # Execute: complete A, then B
        # Verify: D not triggered yet (waiting for C)
        # Execute: complete C
        # Verify: D now triggered
```

## Avoiding Common Mistakes

| Mistake | Correct Approach |
|---------|------------------|
| Using PostgreSQL container | Use SQLite with `aiosqlite` |
| Importing all models in conftest | Import only needed models to avoid NULLS FIRST issues |
| Sharing test data between tests | Use function-scoped fixtures |
| Testing against production DB | Use temp file or in-memory SQLite |
| **Using AsyncMock/MagicMock** | **Use real classes with real DB** |
| **Mocking orchestrator** | **Use LocalOrchestrator with test executor** |
| **Mocking services** | **Instantiate real service classes** |
| **Testing only happy path** | **Include error cases, edge cases, boundaries** |
| **Testing interface only** | **Verify business logic and state changes** |
| Mocking database operations | Use real SQLite operations |
| Running external services | Mock ONLY external vendor APIs, use TestClient for internal API |

## Real Infrastructure Integration Tests

For testing against REAL infrastructure servers (Prefect, MLflow, Centrifugo), use the integration test framework in `tests/integration/`.

### Two Testing Modes

| Mode | Flag | Use Case |
|------|------|----------|
| Ephemeral | `--run-integration` | CI/CD, fresh servers per session |
| Sandbox | `--use-sandbox` | Development, persistent servers |

```bash
# Ephemeral mode (starts/stops servers per test session)
uv run pytest tests/integration/ --run-integration

# Sandbox mode (uses persistent sandbox)
uv run pytest tests/integration/ --use-sandbox

# Manage sandbox manually
python tests/integration/sandbox.py start
python tests/integration/sandbox.py status
python tests/integration/sandbox.py stop
```

### Test Sandbox Features

The sandbox (`tests/integration/sandbox.py`) provides:
- **Persistent infrastructure** - Survives between pytest runs
- **Upgrade checking** - Detects when migrations needed
- **Full stack** - API, Worker, Centrifugo, Prefect, MLflow
- **State persistence** - In `~/.optaic-test-sandbox/`

### Writing Integration Tests

```python
import pytest

pytestmark = pytest.mark.integration

class TestPrefectIntegration:
    def test_deployment_returns_real_id(self, prefect_server: str) -> None:
        """Test creating deployment returns real UUID."""
        from prefect.client.orchestration import get_client
        import asyncio

        async def verify():
            async with get_client() as client:
                deployment_id = await client.create_deployment(...)
                assert deployment_id is not None  # Real UUID!

        asyncio.run(verify())
```

### Available Fixtures

| Fixture | Mode | Description |
|---------|------|-------------|
| `prefect_server` | Ephemeral | Real Prefect API URL |
| `mlflow_server` | Ephemeral | Real MLflow tracking URI |
| `centrifugo_server` | Ephemeral | Real Centrifugo connection info |
| `sandbox` | Sandbox | Full sandbox instance |
| `unified_*` | Both | Auto-selects based on mode |

### What Integration Tests Verify

- **Prefect**: Real `deployment_id`, `flow_run_id`, `task_run_id`
- **MLflow**: Real `experiment_id`, `run_id`, metrics persistence
- **Centrifugo**: Real WebSocket publishing, channel patterns

## CI/CD Testing

Tests run in CI without Docker:

```yaml
# .github/workflows/test.yml (example)
jobs:
  unit-tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest --ignore=tests/integration --tb=short

  integration-tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest tests/integration/ --run-integration
```
