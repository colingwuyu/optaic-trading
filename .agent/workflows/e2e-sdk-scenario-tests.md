---
description: Design and implement E2E scenario tests using Python SDK to verify business logic and improve SDK usability
---

# E2E SDK Scenario Testing Workflow

This workflow guides the design and implementation of end-to-end tests using the Python SDK. These tests serve dual purposes:
1. **Verify System Correctness**: Test the full stack (SDK → API → Database)
2. **Validate SDK Design**: Ensure the SDK is intuitive and user-friendly

## CRITICAL: SDK-ONLY REQUIREMENT

**E2E tests must ONLY use the SDK. NO direct database access allowed.**

### Why This Matters

| Anti-Pattern | Problem |
|--------------|---------|
| Direct DB writes (`db_session.add()`) | Tests work but users can't replicate |
| Importing `libs.db.models.*` | Tests bypass SDK, miss SDK bugs |
| Creating fixtures via SQLAlchemy | Hides missing SDK features |
| Using `test_engine` for data setup | Real users don't have DB access |

### The Principle

If something can't be done via SDK, it's a **missing SDK feature** that needs development:
- Tests reveal SDK gaps and usability issues
- Tests serve as living documentation for SDK usage
- Awkward test code reveals awkward SDK design

### Anti-Pattern Examples

```python
# WRONG: Direct database access
from libs.db.models.identity import Principal, Tenant
from libs.db.models.resource import Resource

async def bad_fixture(test_engine):
    async with AsyncSession(test_engine) as session:
        tenant = Tenant(id=uuid4(), name="Test")  # WRONG!
        session.add(tenant)
        await session.commit()
```

```python
# CORRECT: SDK-only approach
async def good_fixture(sdk_client):
    sdk_client.set_principal_id(uuid4())
    sdk_client.set_tenant_id(uuid4())

    # SDK creates tenant, principal, root resource, RBAC automatically
    tenant = await sdk_client.tenants.create(name="Test")
    return tenant
```

---

## Phase 1: Scenario Discovery

### 1.1 Identify Business Domain Features

Review implemented features to identify testable scenarios:

```bash
# Check implemented services and SDK methods
ls apps/api/services/
ls apps/api/routers/
ls libs/sdk_py/
```

Map features to SDK methods:

| Feature Area | SDK Client | Methods |
|--------------|------------|---------|
| Tenants | `client.tenants` | `create()`, `list()` |
| Principals | `client.principals` | `create()`, `list()` |
| Resources | `client.resources` | `create()`, `get()`, `update()`, `delete()` |
| RBAC | `client.rbac` | `grant()`, `revoke()`, `list_grants()` |
| Activities | `client.activities` | `list()` |
| Chat | `client.chat` | `create_channel()`, `send_message()` |
| Pipelines | `client.pipelines` | `submit_definition()`, `create_instance()` |
| Experiments | `client.experiments` | `create()`, `run()`, `update()` |
| Signals | `client.signals` | `list()`, `register()`, `validate()` |

### 1.2 Design Case Study Scenarios

Each case study should represent a **coherent business workflow**:

**Good Scenario Design:**
```
Case Study: Quantitative Researcher Daily Workflow
1. Create a project for today's research
2. Create an expression experiment
3. Run the experiment to preview results
4. Verify audit trail captures all actions
```

**Bad Scenario Design:**
```
# BAD: Isolated operations without business context
test_create_resource()
test_update_resource()
test_delete_resource()
```

---

## Phase 2: Test Infrastructure Setup

### 2.1 SDK-Only Fixture Pattern

```python
"""E2E Test Fixtures - tests/e2e/conftest.py"""

import pytest_asyncio
from uuid import uuid4
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from libs.sdk_py import AsyncPlatformClient


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Base SDK client with ASGI transport."""
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    client = AsyncPlatformClient(
        base_url="http://test",
        client=httpx_client,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="function")
async def sdk_with_tenant(sdk_client):
    """SDK client with tenant bootstrapped via SDK.

    The tenants.create() API automatically:
    - Creates the Tenant record
    - Creates the calling Principal (owner)
    - Creates a TenantRoot resource
    - Sets up default role permissions
    - Grants owner role to the caller
    """
    tenant_id = uuid4()
    principal_id = uuid4()

    sdk_client.set_principal_id(principal_id)
    sdk_client.set_tenant_id(tenant_id)

    # SDK call - no direct DB access!
    tenant = await sdk_client.tenants.create(name=f"TestTenant-{tenant_id}")

    return {
        "client": sdk_client,
        "tenant_id": tenant["id"],
        "principal_id": principal_id,
        "root_resource_id": tenant.get("root_resource_id"),
    }


@pytest_asyncio.fixture(scope="function")
async def sdk_with_space(sdk_with_tenant):
    """SDK client with tenant and Space via SDK."""
    client = sdk_with_tenant["client"]
    root_resource_id = sdk_with_tenant["root_resource_id"]

    # SDK call - no direct DB access!
    space = await client.resources.create(
        resource_type="Space",
        parent_id=root_resource_id,
        name="Test Space",
    )

    return {
        **sdk_with_tenant,
        "space_id": space["id"],
    }
```

---

## Phase 3: Writing Scenario Tests

### 3.1 Test Structure Pattern

```python
class TestCaseStudy_QuantResearchWorkflow:
    """Case Study: Quantitative Researcher builds an experiment.

    Persona: Quant researcher exploring alpha ideas
    Goal: Create, test, and iterate on expressions
    Success: Experiment runs successfully with audit trail
    """

    async def test_full_research_workflow(self, sdk_with_space):
        """
        Scenario: Researcher creates and runs an experiment

        Given: A researcher with a project space
        When: They create and run an experiment
        Then: Results are returned with audit trail
        """
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Step 1: Create a project via SDK
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Momentum Signal Research",
        )
        assert project["name"] == "Momentum Signal Research"

        # Step 2: Create an experiment via SDK
        experiment = await client.experiments.create(
            parent_id=project["id"],
            name="20-day Momentum",
            expression="MEAN(close, 20)",
        )
        assert "id" in experiment

        # Step 3: Verify audit trail via SDK
        activities = await client.activities.list(resource_id=project["id"])
        actions = [a["action"] for a in activities]
        assert len(activities) >= 2  # resource.created + experiment.created
```

### 3.2 Multi-User Testing via SDK

```python
async def test_multi_user_workflow(self, sdk_with_space):
    """Test involving multiple users."""
    client = sdk_with_space["client"]
    space_id = sdk_with_space["space_id"]

    # Create another user via SDK (not direct DB!)
    other_user = await client.principals.create(
        display_name="Other User",
        email=f"other-{uuid4()}@example.com",
    )

    # Create a project
    project = await client.resources.create(
        resource_type="Project",
        parent_id=space_id,
        name="Shared Project",
    )

    # Grant role via SDK
    grant = await client.rbac.grant(
        subject_principal_id=other_user["id"],
        role_name="viewer",
        scope_resource_id=project["id"],
    )
    assert grant is not None
```

---

## Phase 4: SDK Design Feedback Loop

### When Tests Reveal SDK Gaps

If you can't implement a test via SDK, that's a **missing SDK feature**:

1. **Document** the gap in the test file with `# TODO(SDK)` comment
2. **Implement** the missing SDK method in `libs/sdk_py/`
3. **Update** the test to use the new SDK method
4. **Verify** all tests pass

### SDK Usability Checklist

| Criterion | Question | Red Flag |
|-----------|----------|----------|
| **Discoverability** | Can I find the method? | Buried in unexpected location |
| **Naming** | Does name match intent? | `register` vs `create` confusion |
| **Parameters** | Are required params obvious? | Too many, unclear names |
| **Response** | Does response include what I need? | Missing `id`, `name` |
| **Consistency** | Similar ops work similarly? | `create()` vs `submit()` |

---

## Phase 5: Running E2E Tests

```bash
# Run all E2E tests
uv run pytest tests/e2e/ -xvs

# Run specific case study
uv run pytest tests/e2e/test_case_studies.py::TestCaseStudy1 -xvs

# Run with coverage
uv run pytest tests/e2e/ --cov=libs/sdk_py --cov-report=term-missing
```

---

## Summary

| Rule | Rationale |
|------|-----------|
| **SDK-ONLY** | Tests must use real SDK → API → DB path |
| **No DB imports** | `libs.db.models.*` forbidden in E2E tests |
| **No SQLAlchemy** | `AsyncSession`, `db_session` forbidden |
| **Missing feature = SDK gap** | If you can't do it via SDK, add the SDK method |
