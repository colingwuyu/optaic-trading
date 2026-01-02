# Testing Patterns for OptAIC

This document defines how to write and run tests in the OptAIC project. **All tests must work without Docker or external services.**

## Testing Philosophy

1. **Unit tests** - Fast, isolated, no I/O (use mocks for external calls)
2. **Integration tests** - Use SQLite, test against local wheel install
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

## Mocking External Services

For tests that need external services, use mocks:

```python
# Mock HTTP calls
from unittest.mock import patch, AsyncMock

@patch("httpx.AsyncClient.get")
async def test_external_api(mock_get):
    mock_get.return_value = AsyncMock(
        status_code=200,
        json=lambda: {"data": "test"}
    )
    # Test code that calls external API

# Mock Redis
@patch("redis.asyncio.Redis.from_url")
async def test_with_redis(mock_redis):
    mock_client = AsyncMock()
    mock_redis.return_value = mock_client
    # Test code
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

## Avoiding Common Mistakes

| Mistake | Correct Approach |
|---------|------------------|
| Using PostgreSQL container | Use SQLite with `aiosqlite` |
| Importing all models in conftest | Import only needed models to avoid NULLS FIRST issues |
| Sharing test data between tests | Use function-scoped fixtures |
| Testing against production DB | Use temp file or in-memory SQLite |
| Mocking database operations | Use real SQLite operations |
| Running external services | Mock external calls, use TestClient for API |

## CI/CD Testing

Tests run in CI without Docker:

```yaml
# .github/workflows/test.yml (example)
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest --tb=short
```
