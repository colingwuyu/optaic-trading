---
trigger: model_decision
description: Rules for unit tests
---

# Definition of Done & Quality Policy

## 1. Unit Tests (Strict)
The agent must ensure that all code implementations and resulting tasks, excluding pure documentation updates, have passing unit tests before reporting completion to the user.

- **Pre-report verification:** Always run 'uv run pytest'.
- **Zero Warnings:** Tests must execute without warnings (deprecation, linting, etc).
- **Environment:** Use SQLite (in-memory/tempfile) with 'poolclass=NullPool'.
- **Configuration:** 'conftest.py' must use session-scoped engine fixtures and function-scoped rollbacks.
- **Fail Check:** Do not proceed if tests fail. Troubleshoot and fix immediately.

## 2. NO MOCKS Policy (CRITICAL)

**Mocks are NOT ALLOWED for internal application logic.** Use real database sessions and ORM models.

| Instead of... | Use... |
|---------------|--------|
| `AsyncMock(spec=Service)` | Real service with `db_session` fixture |
| `MagicMock(spec=AsyncSession)` | Real `db_session` from conftest.py |
| `patch("service.method")` | Instantiate real service class |
| Mock data dictionaries | Real database records via ORM |
| Raw SQL for test data | ORM model instances |

**Only exception:** External third-party APIs (Bloomberg, vendor APIs).

## Anti-Patterns (FORBIDDEN)

### Empty Tests
```python
# FORBIDDEN: Tests that just pass do nothing
async def test_something(self) -> None:
    """Would need a mock session."""
    pass  # <-- This is a FAKE test!
```

### Silent Catch-and-Pass
```python
# FORBIDDEN: Hiding failures with try/except pass
try:
    result = await service.do_something()
    assert result is not None
except ImportError:
    pass  # <-- This hides real failures!
except Exception:
    pass  # <-- This prevents error discovery!
```

### Dependency Policy (CRITICAL)

**All imports must be in pyproject.toml.** If a test imports a package:
- The package MUST be listed in `[project.dependencies]` or `[dependency-groups.dev]`
- Import errors should FAIL tests loudly - they indicate broken project setup
- `pytest.importorskip()` is NOT an excuse for missing dependencies

### Correct Patterns
```python
# CORRECT: Let exceptions propagate for investigation
result = await service.do_something()  # Will fail loudly if broken
assert result is not None

# CORRECT: Test edge cases with meaningful assertions
try:
    await db_session.execute(...)  # FK constraint might fire
except IntegrityError:
    pass  # Constraint fired = expected behavior (document why!)
else:
    # Constraint didn't fire - verify data is handled correctly
    assert result.status == "handled"

# WRONG: Never skip import errors - fix pyproject.toml instead!
# try:
#     import missing_package
# except ImportError:
#     pass  # <-- FORBIDDEN: Add to pyproject.toml!
```

## 3. Multi-Account Sandbox Testing

For RBAC, audit, and domain logic tests, use the multi-account sandbox:

```python
from apps.api.tests.conftest import (
    SandboxEnvironment,
    sandbox_env,          # Creates Alpha/Beta tenants
    sandbox_with_resources,
    create_resource,
    create_role_binding,
    create_activity,
    create_lineage_edge,
)

@pytest.mark.asyncio
async def test_cross_tenant_isolation(db_session, sandbox_env):
    """Test that tenants cannot see each other's data."""
    alpha = sandbox_env.tenant_alpha
    beta = sandbox_env.tenant_beta

    # Create resource in Alpha tenant
    resource_id = await create_resource(
        db_session, alpha.id, alpha.admin.id,
        "DatasetInstance", "Private Data",
        parent_id=alpha.spaces[0]
    )

    # Query from Beta tenant - should NOT see Alpha's resource
    stmt = select(Resource).where(Resource.tenant_id == beta.id)
    result = await db_session.execute(stmt)
    assert resource_id not in [r.id for r in result.scalars().all()]
```

### Sandbox Structure

| Object | Description |
|--------|-------------|
| `sandbox_env.tenant_alpha` | First tenant with admin, analysts, viewers |
| `sandbox_env.tenant_beta` | Second tenant with admin, analysts, viewers |
| `sandbox_env.external_user` | User with no access to either tenant |
| `tenant.admin` | Admin user with full permissions |
| `tenant.analysts` | List of analyst users (read/write) |
| `tenant.viewers` | List of viewer users (read-only) |
| `tenant.spaces` | List of space resource IDs |

### Actor Context

```python
# Get ActorContext for RBAC testing
actor = sandbox_env.tenant_alpha.admin.to_actor()
# Returns: ActorContext(id=UUID, tenant_id=UUID, traits={"role": "admin"}, kind="user")
```

## 4. Test Categories

### RBAC/Tenant Isolation Tests
- Cross-tenant resource visibility
- Role-based permission enforcement
- RBAC hierarchy inheritance
- Role binding revocation

### Audit Log Tests
- Activity creation with all fields
- Activity tenant isolation
- Outbox pattern for async processing
- Activity visibility scoping (private, resource, tenant)

### Lineage Tests
- Lineage edge creation and querying
- LineageResolver upstream/downstream resolution
- Diamond pattern handling (deduplication)
- Upstream status tracking

### Domain Logic Tests
- Service create/update/delete operations
- DTO serialization
- Activity emission (mock `record_activity_with_outbox`)
- Guardrails validation at gates

## 5. Documentation Updates (Mandatory)
Every task involving code changes MUST include a review and update of relevant documentation.

**Target Audiences:**
1. **DevOps**: Update 'infra/' docs, deployment guides, or artifactory instructions if infrastructure changes.
2. **System Developer**: Update 'docs/arch', 'README.md', or code comments if logic/patterns change.
3. **Frontend Developer**: Update component docs or API usage guides if UI/API changes.
4. **Quant/Data Team**: Update SDK docs ('libs/sdk_py'), Jupyter examples, or Model definitions if domain logic changes.

**Rule:**
- If you change how it works, you must change how it is documented.
- Check 'README.md' and 'docs/' hierarchy for stale information.

## 6. Technical Requirements (Testing)
- **Runner**: 'uv run pytest'
- **Database**: SQLite only (no Docker).
- **Asyncio**: Use session-scoped event loops and engine fixtures to avoid 'pytest-asyncio' scope errors.
- **Pragmas**: 'foreign_keys=OFF' for audit log resilience in tests.
- **ORM Only**: Use SQLAlchemy ORM for data creation, not raw SQL (UUID handling).