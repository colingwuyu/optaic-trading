import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from apps.api.main import app
from libs.core.rbac.models import GLOBAL_RESOURCE_TYPE
from libs.db.models.rbac import RolePermission
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_subscribe_requires_permission():
    owner_id = uuid.uuid4()
    viewer_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Sub Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(viewer_id), "display_name": "Viewer"},
        )
        assert principal_response.status_code == 201

        subscribe_response = await client.post(
            "/subscriptions",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={"resource_id": root_resource_id, "scope": "resource"},
        )
        assert subscribe_response.status_code == 403


@pytest.mark.asyncio
async def test_subscription_allows_activity_visibility():
    owner_id = uuid.uuid4()
    viewer_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Feed Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(viewer_id), "display_name": "Viewer"},
        )
        assert principal_response.status_code == 201

        space_a = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Space", "parent_id": root_resource_id, "name": "A"},
        )
        assert space_a.status_code == 201
        space_a_id = space_a.json()["id"]

        space_b = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Space", "parent_id": root_resource_id, "name": "B"},
        )
        assert space_b.status_code == 201
        space_b_id = space_b.json()["id"]

        space_c = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Space", "parent_id": root_resource_id, "name": "C"},
        )
        assert space_c.status_code == 201
        space_c_id = space_c.json()["id"]

        grant_response = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(viewer_id),
                "role_name": "viewer",
                "scope_resource_id": space_a_id,
            },
        )
        assert grant_response.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with AsyncSessionLocal() as session:
            await session.execute(
                insert(RolePermission).values(
                    tenant_id=tenant_id,
                    resource_type=GLOBAL_RESOURCE_TYPE,
                    role_name="subscriber",
                    perm_name="SUBSCRIBE_RESOURCE",
                )
            )
            await session.commit()

        grant_subscriber = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(viewer_id),
                "role_name": "subscriber",
                "scope_resource_id": space_b_id,
            },
        )
        assert grant_subscriber.status_code == 201

        subscribe_response = await client.post(
            "/subscriptions",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={"resource_id": space_b_id, "scope": "resource"},
        )
        assert subscribe_response.status_code == 201

        update_response = await client.patch(
            f"/resources/{space_b_id}",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "B-updated"},
        )
        assert update_response.status_code == 200

        update_response_c = await client.patch(
            f"/resources/{space_c_id}",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "C-updated"},
        )
        assert update_response_c.status_code == 200

        feed_response = await client.get(
            "/activities",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert feed_response.status_code == 200
        resource_ids = {
            item["resource"]["resource_id"]
            for item in feed_response.json()["items"]
        }
        assert space_a_id in resource_ids
        assert space_b_id in resource_ids
        assert space_c_id not in resource_ids
