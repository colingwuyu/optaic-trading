import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app


@pytest.mark.asyncio
async def test_realtime_token_denies_unauthorized_channel():
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
            json={"name": "Realtime Tenant"},
        )
        assert tenant_response.status_code == 201
        tenant_data = tenant_response.json()
        tenant_id = uuid.UUID(tenant_data["id"])
        root_resource_id = tenant_data["root_resource_id"]

        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(viewer_id), "display_name": "Viewer"},
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

        channel_response = await client.post(
            "/chat/channels",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "parent_id": root_resource_id,
                "channel_kind": "group",
                "name": "Private",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["id"]

        token_response = await client.post(
            "/realtime/token",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={"channels": [f"t:{tenant_id}:c:{channel_id}"]},
        )
        assert token_response.status_code == 403
        detail = token_response.json()["detail"]
        assert "denied_channels" in detail


@pytest.mark.asyncio
async def test_realtime_token_allows_owner_channels():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Realtime Owner"},
        )
        assert tenant_response.status_code == 201
        tenant_data = tenant_response.json()
        tenant_id = uuid.UUID(tenant_data["id"])
        root_resource_id = tenant_data["root_resource_id"]

        channel_response = await client.post(
            "/chat/channels",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "parent_id": root_resource_id,
                "channel_kind": "group",
                "name": "General",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["id"]

        channels = [
            f"t:{tenant_id}:u:{owner_id}",
            f"t:{tenant_id}:c:{channel_id}",
        ]
        token_response = await client.post(
            "/realtime/token",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"channels": channels},
        )
        assert token_response.status_code == 200
        data = token_response.json()
        assert data["connection_token"]
        assert set(data["subscriptions"].keys()) == set(channels)
        for token in data["subscriptions"].values():
            assert token


@pytest.mark.asyncio
async def test_realtime_bootstrap_filters_channels_and_subscriptions():
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
            json={"name": "Realtime Bootstrap"},
        )
        assert tenant_response.status_code == 201
        tenant_data = tenant_response.json()
        tenant_id = uuid.UUID(tenant_data["id"])
        root_resource_id = tenant_data["root_resource_id"]

        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(viewer_id), "display_name": "Viewer"},
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

        channel_response = await client.post(
            "/chat/channels",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "parent_id": root_resource_id,
                "channel_kind": "group",
                "name": "General",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["id"]

        subscribe_response = await client.post(
            "/subscriptions",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"resource_id": root_resource_id, "scope": "resource"},
        )
        assert subscribe_response.status_code == 201

        viewer_bootstrap = await client.get(
            "/realtime/bootstrap",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert viewer_bootstrap.status_code == 200
        viewer_data = viewer_bootstrap.json()
        viewer_inbox = f"t:{tenant_id}:u:{viewer_id}"
        assert viewer_data["inbox_channel"] == viewer_inbox
        assert viewer_data["chat_channels"] == []
        assert viewer_data["resource_subscriptions"] == []
        assert set(viewer_data["subscription_tokens"].keys()) == {viewer_inbox}

        owner_bootstrap = await client.get(
            "/realtime/bootstrap",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert owner_bootstrap.status_code == 200
        owner_data = owner_bootstrap.json()
        owner_inbox = f"t:{tenant_id}:u:{owner_id}"
        assert owner_data["inbox_channel"] == owner_inbox
        assert {channel["id"] for channel in owner_data["chat_channels"]} == {
            str(channel_id)
        }
        assert {sub["resource_id"] for sub in owner_data["resource_subscriptions"]} == {
            str(root_resource_id)
        }
        owner_channels = {
            owner_inbox,
            f"t:{tenant_id}:c:{channel_id}",
            f"t:{tenant_id}:r:{root_resource_id}",
        }
        assert set(owner_data["subscription_tokens"].keys()) == owner_channels
