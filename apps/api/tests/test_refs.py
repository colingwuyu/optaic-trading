import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.main import app
from libs.db.models.activity import Activity, Outbox
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_branch_create_list_delete_writes_activity_and_outbox():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Branch Tenant"},
        )
        assert tenant_response.status_code == 201
        tenant_data = tenant_response.json()
        tenant_id = uuid.UUID(tenant_data["id"])
        root_resource_id = tenant_data["root_resource_id"]

        dataset_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Dataset",
                "parent_id": root_resource_id,
                "name": "Dataset",
            },
        )
        assert dataset_response.status_code == 201
        dataset_id = uuid.UUID(dataset_response.json()["id"])

        branch_response = await client.post(
            f"/refs/{dataset_id}/branches",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"ref_name": "feature-x"},
        )
        assert branch_response.status_code == 201

        list_response = await client.get(
            f"/refs/{dataset_id}/branches",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert list_response.status_code == 200
        refs = {item["ref_name"] for item in list_response.json()}
        assert {"main", "feature-x"}.issubset(refs)

        delete_response = await client.delete(
            f"/refs/{dataset_id}/branches/feature-x",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert delete_response.status_code == 200

        activity_response = await client.get(
            "/activities",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            params={"resource_id": str(dataset_id)},
        )
        assert activity_response.status_code == 200
        actions = {item["action"] for item in activity_response.json()["items"]}
        assert "branch.created" in actions
        assert "branch.deleted" in actions

    async with AsyncSessionLocal() as session:
        activity_rows = await session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.resource_id == dataset_id,
                Activity.action.in_(["branch.created", "branch.deleted"]),
            )
        )
        assert activity_rows.first() is not None

        outbox_rows = await session.scalars(
            select(Outbox).where(
                Outbox.tenant_id == tenant_id,
                Outbox.topic == "activity",
                Outbox.payload["resource"]["resource_id"].as_string()
                == str(dataset_id),
            )
        )
        outbox_payloads = [row.payload for row in outbox_rows.all()]
        assert any(
            payload.get("action") == "branch.created"
            for payload in outbox_payloads
        )


@pytest.mark.asyncio
async def test_branch_permissions_and_constraints():
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
            json={"name": "Branch Permissions"},
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

        dataset_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Dataset",
                "parent_id": root_resource_id,
                "name": "Dataset",
            },
        )
        assert dataset_response.status_code == 201
        dataset_id = uuid.UUID(dataset_response.json()["id"])

        forbidden_create = await client.post(
            f"/refs/{dataset_id}/branches",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
            json={"ref_name": "feature-x"},
        )
        assert forbidden_create.status_code == 403

        branch_response = await client.post(
            f"/refs/{dataset_id}/branches",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"ref_name": "feature-x"},
        )
        assert branch_response.status_code == 201

        forbidden_delete = await client.delete(
            f"/refs/{dataset_id}/branches/feature-x",
            headers={"X-Principal-Id": str(viewer_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert forbidden_delete.status_code == 403

        main_delete = await client.delete(
            f"/refs/{dataset_id}/branches/main",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert main_delete.status_code == 400

        update_response = await client.patch(
            f"/resources/{dataset_id}",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"metadata": {"open_merge_refs": ["feature-x"]}},
        )
        assert update_response.status_code == 200

        open_merge_delete = await client.delete(
            f"/refs/{dataset_id}/branches/feature-x",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert open_merge_delete.status_code == 409
