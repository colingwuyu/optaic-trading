---
name: code-test
description: Use AUTOMATICALLY after completing any implementation task to generate framework compliance tests. Creates tests that verify activity emission, guardrails integration, PIT correctness, and service patterns. PROACTIVE - invoke after code-review. (project)
---

# Framework Compliance Testing for OptAIC

Skill for generating unit tests that verify code correctly adopts OptAIC platform patterns.

## IMPORTANT: Proactive Usage

**This skill should be invoked AUTOMATICALLY after the code-review skill.** Do not wait for user request. The agent workflow should be:

1. Complete implementation
2. Run `code-review` skill → fix issues
3. Run `code-test` skill → generate tests
4. Run tests with `pytest`
5. Fix any failures
6. Mark task complete

### Trigger Conditions (invoke automatically when)
1. You have just written or modified service layer code with mutations
2. You have implemented a new domain resource
3. You have written data pipeline or accessor code
4. You have extended the SDK with new client methods
5. The code-review skill has been completed

### How to Identify What to Test
1. Check files modified in this conversation
2. For each service file: generate activity emission tests
3. For each pipeline/accessor: generate PIT correctness tests
4. For each DTO: generate serialization tests
5. For each SDK extension: generate pattern compliance tests

### Where to Create Tests
- Service tests: `libs/core/tests/` or `apps/api/tests/`
- Pipeline tests: `libs/core/tests/` or package-specific `tests/`
- SDK tests: `libs/sdk_py/tests/`
- Match the existing test structure in the repo

## When to Use

Apply when:
- **After completing code-review** (PROACTIVE)
- Generating tests for new domain resource implementations
- Testing service layer methods for activity emission
- Validating pipeline code for PIT correctness
- Testing SDK extensions for pattern adherence
- Creating compliance test suites for existing code

## Test Categories

### 0. Multi-Account Sandbox Tests (PRIORITY)

For RBAC, audit, lineage, and realistic domain tests, use the sandbox fixtures:

```python
from apps.api.tests.conftest import (
    SandboxEnvironment,
    sandbox_env,
    create_resource,
    create_role_binding,
    create_activity,
    create_lineage_edge,
)

@pytest.mark.asyncio
async def test_cross_tenant_isolation(db_session, sandbox_env):
    """Test tenant isolation with real multi-tenant data."""
    alpha = sandbox_env.tenant_alpha
    beta = sandbox_env.tenant_beta

    # Create resource in Alpha
    resource_id = await create_resource(
        db_session, alpha.id, alpha.admin.id,
        "DatasetInstance", "Alpha Data",
        parent_id=alpha.spaces[0],
    )

    # Query from Beta - should NOT see Alpha's data
    stmt = select(Resource).where(Resource.tenant_id == beta.id)
    result = await db_session.execute(stmt)
    assert resource_id not in [r.id for r in result.scalars().all()]
```

**CRITICAL:** Use ORM models, not raw SQL, for test data creation.

### Test Anti-Patterns (FORBIDDEN)

```python
# FORBIDDEN: Empty test body - fake test that inflates count
async def test_something(self) -> None:
    pass  # <-- NEVER DO THIS!

# FORBIDDEN: Silent catch-and-pass hides real failures
try:
    result = await service.do_something()
except ImportError:
    pass  # <-- NEVER DO THIS!

# FORBIDDEN: "Checking" for dependencies not in pyproject.toml
try:
    import some_package  # Not in pyproject.toml
except ImportError:
    pass  # <-- FIX PYPROJECT.TOML INSTEAD!
```

**Dependency Policy:** All imports must be in `pyproject.toml`. Import errors indicate broken project setup and should FAIL tests, not be silently skipped.

### 1. Activity Emission Tests

Verify all mutations emit correct ActivityEnvelope:

```python
@pytest.mark.asyncio
async def test_create_emits_activity(self, db_session, actor_id, tenant_id):
    service = SignalService(db_session, actor_id, tenant_id)

    with patch("libs.core.activity.record_activity_with_outbox") as mock:
        mock.return_value = AsyncMock()
        await service.create(dto, parent_id)

        mock.assert_called_once()
        envelope = mock.call_args.kwargs["envelope"]
        assert envelope.action == "signal.created"
        assert envelope.actor_principal_id == actor_id
        assert envelope.resource_type == "signal"
```

### 2. Guardrails Integration Tests

Verify validation at lifecycle gates:

```python
@pytest.mark.asyncio
async def test_create_validates_guardrails(self, db_session):
    with patch("optaic.guardrails.GuardrailsEngine.validate_at_gate") as mock:
        mock.return_value = ValidationReport(ok=True)
        await service.create(dto, parent_id)

        mock.assert_called_once()
        assert mock.call_args.kwargs["gate"] == "create"
```

### 3. PIT Correctness Tests

Verify no lookahead bias:

```python
def test_query_respects_knowledge_date(self, db_session):
    # Insert data with future knowledge_date
    insert_price(date="2024-01-01", knowledge_date="2024-01-15")

    # Query as of 2024-01-10 should NOT see this data
    result = accessor.query(as_of="2024-01-01", knowledge_cutoff="2024-01-10")
    assert len(result) == 0
```

### 4. DTO Serialization Tests

Verify DTOs work correctly:

```python
def test_dto_serialization(self):
    dto = SignalCreateDTO(name="test", signal_type="alpha")
    data = dto.model_dump()
    restored = SignalCreateDTO.model_validate(data)
    assert restored == dto
```

### 5. Lazy Import Tests

Verify heavy deps are not top-level:

```python
def test_no_heavy_imports_at_module_level():
    import sys
    # Clear cached imports
    for mod in list(sys.modules.keys()):
        if mod.startswith("libs.core.domain"):
            del sys.modules[mod]

    # Import module - should not import pandas
    import libs.core.domain.signal_service
    assert "pandas" not in sys.modules
```

## Test Generation Workflow

1. **List all files modified** in this conversation
2. **For each modified file**, identify component type
3. **Generate activity emission tests** for all mutation methods (create/update/delete)
4. **Generate guardrails tests** for create/update operations
5. **Generate PIT tests** for any data access code
6. **Generate DTO tests** for any new Pydantic models
7. **Generate lazy import checks** if core modules were modified
8. **Write test files** to appropriate location
9. **Run pytest** to verify tests pass
10. **Fix any failures** before completing

## Test File Naming Convention

Follow the existing patterns:
- `test_<module>_activity.py` - Activity emission tests
- `test_<module>_guardrails.py` - Guardrails integration tests
- `test_<module>_pit.py` - PIT correctness tests
- `test_<module>.py` - General logic tests

Or add to existing test file if one exists for the module.

## Output Format

After generating tests, produce a structured report:

```
## Test Generation Report

### Tests Created
- `path/to/test_file.py`
  - `test_create_emits_activity` - Activity emission
  - `test_update_calls_guardrails` - Guardrails integration
  - ...

### Test Execution Results
```
pytest path/to/test_file.py -v
[output]
```

### Coverage Summary
- Activity Emission: [X mutations covered]
- Guardrails: [X gates tested]
- PIT Correctness: [X/N/A]
- DTO Serialization: [X DTOs tested]

### Status
[ALL TESTS PASS | FAILURES - need fixes]
```

## Pytest Fixtures Available

Use these existing fixtures from the codebase:
- `db_session` - Async database session
- `client` - Test HTTP client
- `actor_id`, `tenant_id` - Test identity context

Check `conftest.py` files for available fixtures before creating new ones.

## Reference Files

- [Sandbox Tests](references/sandbox-tests.md) - Multi-account sandbox testing patterns (PRIORITY)
- [Activity Tests](references/activity-tests.md) - Activity emission test patterns
- [Guardrails Tests](references/guardrails-tests.md) - Validation test patterns
- [Pipeline Tests](references/pipeline-tests.md) - PIT and quality test patterns
- [Framework Tests](references/framework-tests.md) - Generic compliance tests
