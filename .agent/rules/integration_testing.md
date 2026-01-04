---
trigger: model_decision
description: Agent trigger: Load this file when implementing integration tests, testing with real infrastructure servers, or managing the test sandbox.
---

# Integration Testing Rules

Guide for writing and running integration tests against real infrastructure servers.

## 1. Unified Sandbox-Based Testing (CRITICAL)

**ALL tests run against real infrastructure by default:**
- SQLite database (session-scoped)
- Prefect server (real `deployment_id`, `flow_run_id`, `task_run_id`)
- MLflow server (real `experiment_id`, `run_id`, metrics)
- Centrifugo server (real WebSocket publishing)

```bash
# Run all tests (uses sandbox automatically)
pytest

# Run unit tests only
pytest libs/ apps/ optaic/

# Run integration tests only
pytest tests/integration/

# Custom sandbox location
OPTAIC_TEST_SANDBOX_DIR=/custom/path pytest
```

## 2. Test Infrastructure Lifecycle

**Session-scoped infrastructure:**
- Servers start when first test requires them
- Servers persist for entire pytest session
- Cleanup happens automatically via `pytest_unconfigure`
- Each session gets a fresh temp directory for isolation

## 3. Test File Structure

```
tests/integration/
├── __init__.py
├── conftest.py              # Integration-specific fixtures
├── sandbox.py               # Sandbox manager (legacy)
├── test_prefect_integration.py
├── test_mlflow_integration.py
├── test_centrifugo_integration.py
└── tests/
    └── test_sandbox.py      # Unit tests for sandbox manager
```

## 4. Writing Integration Tests

### Mark Tests as Integration
```python
import pytest

pytestmark = pytest.mark.integration

class TestMyFeature:
    def test_something(self, prefect_server: str) -> None:
        # Test code uses real Prefect server
        pass
```

### Available Fixtures (from root conftest.py)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db_session` | function | Async database session (auto-rollback) |
| `test_engine` | session | SQLAlchemy async engine |
| `prefect_server` | session | Real Prefect server URL |
| `mlflow_server` | session | Real MLflow tracking URI |
| `centrifugo_server` | session | Real Centrifugo config dict |
| `prefect_env` | function | Sets `PREFECT_API_URL` env var |
| `mlflow_env` | function | Sets `MLFLOW_TRACKING_URI` env var |

### Example: Testing with Real Prefect

```python
@pytest.mark.asyncio
async def test_create_deployment(prefect_server: str) -> None:
    """Test creating a real deployment."""
    from prefect.client.orchestration import get_client

    async with get_client() as client:
        # Note: The "default" work pool is auto-created by the test fixture
        deployment_id = await client.create_deployment(
            flow_id=flow_id,
            name="test-deployment",
            work_pool_name="default",
        )

        # Verify it's a real UUID
        assert deployment_id is not None

        # Verify via API
        deployment = await client.read_deployment(deployment_id)
        assert deployment.name == "test-deployment"
```

### Example: Testing with Real MLflow

```python
def test_log_metrics(mlflow_server: str) -> None:
    """Test logging metrics to real MLflow."""
    import mlflow

    mlflow.set_tracking_uri(mlflow_server)

    with mlflow.start_run() as run:
        mlflow.log_metric("accuracy", 0.95)

    # Verify persisted
    fetched = mlflow.get_run(run.info.run_id)
    assert fetched.data.metrics["accuracy"] == 0.95
```

## 5. Infrastructure Ports

| Service | Port | Environment Variable |
|---------|------|---------------------|
| Prefect | 14200 | `PREFECT_API_URL` (auto-set) |
| MLflow | 14500 | `MLFLOW_TRACKING_URI` (auto-set) |
| Centrifugo | 14000 | (returned in fixture dict) |

## 6. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPTAIC_TEST_SANDBOX_DIR` | Session temp dir | Sandbox data directory |
| `DATABASE_URL` | Auto (SQLite) | Test database URL |
| `PREFECT_API_URL` | Auto | Set by fixtures |
| `MLFLOW_TRACKING_URI` | Auto | Set by fixtures |

## 7. What to Verify in Integration Tests

### Prefect Tests
- [ ] `deployment_id` is real UUID
- [ ] `flow_run_id` is real UUID
- [ ] `task_run_id` is real UUID
- [ ] Deployment persists in registry
- [ ] Flow run status transitions correctly

### MLflow Tests
- [ ] `experiment_id` is real
- [ ] `run_id` is real UUID
- [ ] Metrics persist after run ends
- [ ] Parameters persist
- [ ] Tags persist
- [ ] Run status transitions (RUNNING → FINISHED)

### Centrifugo Tests
- [ ] API responds to publish
- [ ] Broadcast works
- [ ] JWT tokens are valid
- [ ] Channel patterns work

## 8. CRITICAL: NO MOCKS POLICY

**Mocks are NOT ALLOWED for internal application logic.** This is a non-negotiable requirement.

### Why Mocks Are Forbidden

| Problem | Impact |
|---------|--------|
| Mocks test mock behavior, not code | False positives, bugs slip through |
| AsyncMock hides concurrency bugs | Race conditions undetected |
| MagicMock returns fake values | Logic errors pass tests |
| patch() bypasses real code paths | Integration issues undetected |

### What to Use Instead

| Instead of... | Use... |
|---------------|--------|
| `AsyncMock(spec=OrchestratorAdapter)` | `LocalOrchestrator` with custom executor |
| `MagicMock(spec=AsyncSession)` | Real `db_session` from conftest.py |
| `patch("service.method")` | Instantiate real service class |
| Mock data dictionaries | Real database records via SQL |

### Example: Correct Test Pattern

```python
# CORRECT: Real dependencies
@pytest.mark.asyncio
async def test_pipeline_run_completion(db_session):
    # Create real data in real database
    tenant_id, principal_id = await create_tenant_and_principal(db_session)
    dataset_id = await create_dataset_instance(db_session, tenant_id, principal_id)

    # Use real orchestrator with test executor
    orchestrator = LocalOrchestrator(
        max_workers=2,
        node_executor=lambda *args: {"status": "success", "rows": 100}
    )

    # Instantiate real service
    service = PipelineRunService(orchestrator=orchestrator, status_store=StatusStore(db_session))

    # Execute and verify real state
    result = await service.submit_run(db_session, dataset_id, actor)
    assert result.run_id is not None

    # Verify in real database
    run = await db_session.get(PipelineRun, result.run_id)
    assert run.status in ("queued", "running")
```

### Only Exception: External Third-Party APIs

```python
# ONLY acceptable mock: External vendor APIs we don't control
@patch("httpx.AsyncClient.get")
async def test_bloomberg_data_fetch(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: {"vendor": "data"})
    # Test code that calls Bloomberg API
```

## 9. Anti-Patterns

| Anti-Pattern | Correct Approach |
|--------------|------------------|
| Using `prefect_test_harness()` for integration | Use real Prefect server via fixtures |
| Mocking Centrifugo in integration tests | Use real Centrifugo via fixtures |
| Starting servers in each test | Use session-scoped fixtures |
| Hardcoding ports | Use defined ports (14200, 14500, 14000) |
| Skipping cleanup | Fixtures handle cleanup automatically |
| Using separate testing modes | Use unified sandbox (default) |
| **Using AsyncMock/MagicMock** | **Use real classes with db_session** |
| **Mocking orchestrator** | **Use LocalOrchestrator with test executor** |
| **Mocking services** | **Instantiate real service classes** |
| **Testing only happy path** | **Include error cases, edge cases** |

## 10. CI/CD Integration

Tests run automatically with sandbox infrastructure:

```yaml
# GitHub Actions example (.github/workflows/ci.yml)
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest libs/ apps/ optaic/ -q    # Unit tests
      - run: uv run pytest tests/integration/ -q     # Integration tests
        env:
          OPTAIC_TEST_SANDBOX_DIR: ${{ runner.temp }}/optaic-sandbox
```

## 11. E2E Scenario Testing (SDK-Based)

For **business workflow testing** using the Python SDK, see:
- **Workflow**: `.agent/workflows/e2e-sdk-scenario-tests.md`
- **Tests**: `tests/e2e/test_case_studies.py`

E2E tests complement integration tests:

| Test Type | Focus | Infrastructure |
|-----------|-------|----------------|
| **Integration** | Infrastructure servers (Prefect, MLflow, Centrifugo) | Real servers |
| **E2E Scenario** | Business workflows via SDK | SDK → API → Database |

E2E tests use the SDK to simulate real user workflows, verifying:
- SDK usability and intuitiveness
- Full stack correctness
- Business logic completeness
- Audit trail accuracy

## 12. References

- `conftest.py` (root) - All test infrastructure fixtures
- `tests/integration/conftest.py` - Integration-specific markers
- `.claude/skills/devops-deployment/references/testing-patterns.md` - Testing philosophy
- `.agent/workflows/e2e-sdk-scenario-tests.md` - E2E scenario testing workflow
