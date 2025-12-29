import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import apps.api.attachments_service as attachments_service
from apps.api.main import app
from libs.db.models.activity import Activity
from libs.db.models.chat import MessageAttachment
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_attachment_upload_init_requires_permission(monkeypatch):
    owner_id = uuid.uuid4()
    viewer_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async def fake_presigned_put(**kwargs):
        return "http://signed.local/upload", {"Content-Type": kwargs["content_type"]}

    monkeypatch.setattr(attachments_service, "create_presigned_put", fake_presigned_put)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Attachment Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(viewer_id), "display_name": "Viewer"},
        )
        assert principal_response.status_code == 201

        channel_response = await client.post(
            "/chat/channels",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "parent_id": root_resource_id,
                "channel_kind": "group",
                "name": "Uploads",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["resource_id"]

        forbidden = await client.post(
            "/attachments/upload-init",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "channel_id": channel_id,
                "filename": "design.png",
                "content_type": "image/png",
                "bytes": 1024,
            },
        )
        assert forbidden.status_code == 403

        grant_response = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(viewer_id),
                "role_name": "operator",
                "scope_resource_id": channel_id,
            },
        )
        assert grant_response.status_code == 201

        allowed = await client.post(
            "/attachments/upload-init",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "channel_id": channel_id,
                "filename": "design.png",
                "content_type": "image/png",
                "bytes": 1024,
            },
        )
        assert allowed.status_code == 201
        payload = allowed.json()
        assert payload["presigned_put_url"].startswith("http://signed.local/")


@pytest.mark.asyncio
async def test_attachment_finalize_creates_record_and_activity(monkeypatch):
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async def fake_presigned_put(**kwargs):
        return "http://signed.local/upload", {"Content-Type": kwargs["content_type"]}

    async def fake_head_object(object_key: str):
        return {
            "etag": "deadbeef",
            "content_length": 2048,
            "content_type": "image/png",
            "metadata": {"filename": "design.png", "bytes": "2048"},
        }

    monkeypatch.setattr(attachments_service, "create_presigned_put", fake_presigned_put)
    monkeypatch.setattr(attachments_service, "head_object", fake_head_object)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Attachment Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        channel_response = await client.post(
            "/chat/channels",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "parent_id": root_resource_id,
                "channel_kind": "group",
                "name": "Uploads",
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["resource_id"]

        upload_init = await client.post(
            "/attachments/upload-init",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "channel_id": channel_id,
                "filename": "design.png",
                "content_type": "image/png",
                "bytes": 2048,
            },
        )
        assert upload_init.status_code == 201
        object_key = upload_init.json()["object_key"]

        message_response = await client.post(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Attachment ready"},
        )
        assert message_response.status_code == 201
        message_id = message_response.json()["id"]

        finalize_response = await client.post(
            "/attachments/finalize",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "message_id": message_id,
                "object_key": object_key,
                "checksum": "md5:deadbeef",
            },
        )
        assert finalize_response.status_code == 201
        finalize_payload = finalize_response.json()
        assert finalize_payload["filename"] == "design.png"

    async with AsyncSessionLocal() as session:
        attachment = await session.scalar(
            select(MessageAttachment).where(
                MessageAttachment.tenant_id == tenant_id,
                MessageAttachment.object_key == object_key,
            )
        )
        assert attachment is not None
        assert attachment.bytes == 2048

        activity = await session.scalar(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.resource_id == uuid.UUID(channel_id),
                Activity.action == "attachment.added",
            )
        )
        assert activity is not None
