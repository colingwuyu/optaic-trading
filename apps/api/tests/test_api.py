import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from libs.core.rbac.models import Permission

@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["ok"] is True

@pytest.mark.asyncio
async def test_resource_activity_and_rbac_flow():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Acme"},
        )
        assert tenant_response.status_code == 201
        tenant_data = tenant_response.json()
        assert tenant_data["id"] == str(tenant_id)
        root_resource_id = tenant_data["root_resource_id"]

        space_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Space",
                "parent_id": root_resource_id,
                "name": "Product",
            },
        )
        assert space_response.status_code == 201
        space_id = space_response.json()["id"]

        subspace_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Subspace",
                "parent_id": space_id,
                "name": "Planning",
            },
        )
        assert subspace_response.status_code == 201
        subspace_id = subspace_response.json()["id"]

        project_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Project",
                "parent_id": subspace_id,
                "name": "Roadmap",
            },
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        activity_response = await client.get(
            "/activities",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            params={"limit": 1},
        )
        assert activity_response.status_code == 200
        activity_page = activity_response.json()
        actions = {item["action"] for item in activity_page["items"]}
        assert "resource.created" in actions
        assert activity_page["next_cursor"] is not None
        first_item = activity_page["items"][0]
        assert first_item["version"] == "1"
        assert "event_id" in first_item
        assert first_item["actor"]["principal_id"] == str(owner_id)
        assert "resource" in first_item

        next_page_response = await client.get(
            "/activities",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            params={"limit": 1, "cursor": activity_page["next_cursor"]},
        )
        assert next_page_response.status_code == 200
        assert len(next_page_response.json()["items"]) == 1

        viewer_id = uuid.uuid4()
        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "id": str(viewer_id),
                "display_name": "Viewer",
                "email": "viewer@example.com",
            },
        )
        assert principal_response.status_code == 201

        grant_response = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(viewer_id),
                "role_name": "viewer",
                "scope_resource_id": root_resource_id,
            },
        )
        assert grant_response.status_code == 201

        effective_response = await client.get(
            "/rbac/effective",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            params={"resource_id": project_id, "principal_id": str(viewer_id)},
        )
        assert effective_response.status_code == 200
        permissions = set(effective_response.json()["permissions"])
        assert Permission.RESOURCE_READ.value in permissions
        assert Permission.VIEW_ACTIVITY_FEED.value in permissions

        tree_response = await client.get(
            f"/resources/{space_id}/tree",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            params={"depth": 2},
        )
        assert tree_response.status_code == 200
        tree_payload = tree_response.json()
        assert tree_payload["resource"]["id"] == space_id
        assert len(tree_payload["children"]) == 1

        viewer_feed = await client.get(
            "/activities",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert viewer_feed.status_code == 200
        viewer_actions = {item["action"] for item in viewer_feed.json()["items"]}
        assert "resource.created" in viewer_actions

@pytest.mark.asyncio
async def test_tenant_list_scoped_to_principal():
    owner_one = uuid.uuid4()
    owner_two = uuid.uuid4()
    tenant_one = uuid.uuid4()
    tenant_two = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_one), "X-Tenant-Id": str(tenant_one)},
            json={"name": "Tenant One"},
        )
        assert first_response.status_code == 201
        first_tenant_id = first_response.json()["id"]

        second_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_two), "X-Tenant-Id": str(tenant_two)},
            json={"name": "Tenant Two"},
        )
        assert second_response.status_code == 201

        list_response = await client.get(
            "/tenants",
            headers={"X-Principal-Id": str(owner_one), "X-Tenant-Id": str(tenant_one)},
        )
        assert list_response.status_code == 200
        tenant_ids = {tenant["id"] for tenant in list_response.json()}
        assert tenant_ids == {first_tenant_id}
