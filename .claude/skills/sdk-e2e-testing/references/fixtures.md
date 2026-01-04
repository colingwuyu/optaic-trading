# E2E SDK Test Fixtures

## Test Infrastructure Setup

### Fixture Pattern for SDK Testing

Use this fixture pattern for E2E tests:

```python
"""E2E Test Fixtures - tests/e2e/conftest.py"""

import pytest_asyncio
from uuid import uuid4
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.main import app
from libs.sdk_py import AsyncPlatformClient
from libs.db.models.identity import Principal, Tenant
from libs.db.models.resource import Resource
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.core.rbac.models import Permission


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Base SDK client with ASGI transport for in-process testing."""
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
async def sdk_with_tenant(test_engine, sdk_client):
    """SDK client with tenant and authenticated principal.

    Commits data to DB so API can see it (E2E tests need committed data).
    """
    tenant_id = uuid4()
    principal_id = uuid4()

    async with AsyncSession(test_engine) as session:
        # Create tenant
        tenant = Tenant(id=tenant_id, name="Test Tenant")
        session.add(tenant)

        # Create principal
        principal = Principal(
            id=principal_id,
            tenant_id=tenant_id,
            display_name="Test User",
            kind="user",
        )
        session.add(principal)
        await session.commit()

    # Configure SDK with credentials
    sdk_client._principal_id = principal_id
    sdk_client._tenant_id = tenant_id

    yield {
        "client": sdk_client,
        "tenant_id": tenant_id,
        "principal_id": principal_id,
    }


@pytest_asyncio.fixture(scope="function")
async def sdk_with_space(test_engine, sdk_with_tenant):
    """SDK client with tenant, principal, root space, and RBAC permissions."""
    client = sdk_with_tenant["client"]
    tenant_id = sdk_with_tenant["tenant_id"]
    principal_id = sdk_with_tenant["principal_id"]
    space_id = uuid4()

    async with AsyncSession(test_engine) as session:
        # Set up role permissions for admin
        admin_perms = [
            Permission.RESOURCE_READ,
            Permission.RESOURCE_CREATE_CHILD,
            Permission.RESOURCE_UPDATE,
            Permission.RESOURCE_DELETE,
            Permission.RBAC_GRANT,
            Permission.RBAC_REVOKE,
            Permission.VIEW_ACTIVITY_FEED,
            Permission.BRANCH_CREATE,
            Permission.CHANNEL_POST,
            Permission.CHANNEL_VIEW_HISTORY,
        ]
        for perm in admin_perms:
            role_perm = RolePermission(
                tenant_id=tenant_id,
                resource_type="*",
                role_name="admin",
                perm_name=perm.value,
            )
            session.add(role_perm)

        # Create root space
        space = Resource(
            id=space_id,
            tenant_id=tenant_id,
            type="Space",
            parent_id=None,
            owner_principal_id=principal_id,
            name="Test Space",
            status="active",
        )
        session.add(space)

        # Grant admin role
        binding = RoleBinding(
            tenant_id=tenant_id,
            principal_id=principal_id,
            role_name="admin",
            scope_resource_id=space_id,
        )
        session.add(binding)
        await session.commit()

    yield {
        **sdk_with_tenant,
        "space_id": space_id,
    }
```

### Test File Structure

```
tests/
├── e2e/
│   ├── __init__.py
│   ├── conftest.py              # Shared E2E fixtures
│   ├── test_case_studies.py     # Main case study tests
│   ├── test_data_workflows.py   # Data pipeline scenarios
│   ├── test_research_workflows.py  # Research/experiment scenarios
│   ├── test_governance_workflows.py  # RBAC/audit scenarios
│   └── test_collaboration.py    # Chat/versioning scenarios
```
