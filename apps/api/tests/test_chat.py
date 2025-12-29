import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.main import app
from libs.db.models.activity import Outbox
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_chat_actions_write_activity_and_outbox():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Chat Tenant"},
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
                "topic": "Daily updates",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["resource_id"]

        message_response = await client.post(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Hello team"},
        )
        assert message_response.status_code == 201
        message_id = message_response.json()["id"]

        edit_response = await client.patch(
            f"/chat/messages/{message_id}",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Hello team!"},
        )
        assert edit_response.status_code == 200
        assert edit_response.json()["edited_at"] is not None

        delete_response = await client.delete(
            f"/chat/messages/{message_id}",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

        read_response = await client.post(
            f"/chat/channels/{channel_id}/read",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"last_read_message_id": message_id},
        )
        assert read_response.status_code == 200
        assert read_response.json()["last_read_message_id"] == message_id

        activity_response = await client.get(
            "/activities",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            params={"resource_id": channel_id},
        )
        assert activity_response.status_code == 200
        items = activity_response.json()["items"]
        actions = {item["action"] for item in items}
        assert {
            "channel.created",
            "message.posted",
            "message.edited",
            "message.deleted",
            "receipt.read",
        }.issubset(actions)
        message_event = next(
            item for item in items if item["action"] == "message.posted"
        )
        targets = message_event["targets"]
        assert str(channel_id) in targets["chat_channels"]
        assert str(channel_id) in targets["resource_channels"]

    async with AsyncSessionLocal() as session:
        outbox_rows = (
            await session.scalars(
                select(Outbox).where(
                    Outbox.tenant_id == tenant_id,
                    Outbox.topic == "activity",
                    Outbox.payload["resource"]["resource_id"].as_string()
                    == channel_id,
                )
            )
        ).all()
        outbox_actions = {row.payload.get("action") for row in outbox_rows}
        assert {
            "channel.created",
            "message.posted",
            "message.edited",
            "message.deleted",
            "receipt.read",
        }.issubset(outbox_actions)


@pytest.mark.asyncio
async def test_chat_permissions_operator_can_post_edit_delete():
    owner_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Operator Tenant"},
        )
        assert tenant_response.status_code == 201
        tenant_data = tenant_response.json()
        tenant_id = uuid.UUID(tenant_data["id"])
        root_resource_id = tenant_data["root_resource_id"]

        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(operator_id), "display_name": "Operator"},
        )
        assert principal_response.status_code == 201

        grant_response = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(operator_id),
                "role_name": "operator",
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
                "name": "Operators",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["resource_id"]

        post_response = await client.post(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(operator_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Operator note"},
        )
        assert post_response.status_code == 201
        message_id = post_response.json()["id"]

        edit_response = await client.patch(
            f"/chat/messages/{message_id}",
            headers={"X-Principal-Id": str(operator_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Operator update"},
        )
        assert edit_response.status_code == 200
        assert edit_response.json()["edited_at"] is not None

        delete_response = await client.delete(
            f"/chat/messages/{message_id}",
            headers={"X-Principal-Id": str(operator_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_chat_permissions_denied_for_viewer_role():
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
            json={"name": "Permission Tenant"},
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
        channel_id = channel_response.json()["resource_id"]

        post_response = await client.post(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Should fail"},
        )
        assert post_response.status_code == 403

        history_response = await client.get(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert history_response.status_code == 403
