import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.main import app
from libs.core.versioning import create_version, get_current_head, update_ref
from libs.db.models.activity import Activity
from libs.db.models.resource import ResourceRef, ResourceVersion
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_merge_request_flow_requires_approval_and_merges():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "MR Tenant"},
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

    async with AsyncSessionLocal() as session:
        head = await get_current_head(session, dataset_id, ref_name="main")
        assert head is not None
        source_version = await create_version(
            session,
            dataset_id,
            parents=[head.id],
            content={
                "pipeline_refs": ["pipe:v2"],
                "store_refs": [],
                "accessor_refs": [],
                "config": {"note": "source"},
            },
            created_by=owner_id,
        )
        await update_ref(session, dataset_id, "feature-x", source_version.id, owner_id)
        await session.commit()
        target_head_id = head.id
        source_head_id = source_version.id

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        mr_response = await client.post(
            "/merge-requests",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "target_resource_id": str(dataset_id),
                "source_ref": "feature-x",
                "target_ref": "main",
                "title": "Merge feature",
            },
        )
        assert mr_response.status_code == 201
        mr_id = uuid.UUID(mr_response.json()["id"])

        merge_without_approval = await client.post(
            f"/merge-requests/{mr_id}/merge",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert merge_without_approval.status_code == 400

        approve_response = await client.post(
            f"/merge-requests/{mr_id}/approve",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"decision": "approve"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["approvals"] == 1

        merge_response = await client.post(
            f"/merge-requests/{mr_id}/merge",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert merge_response.status_code == 200
        new_version_id = uuid.UUID(merge_response.json()["new_version_id"])

    async with AsyncSessionLocal() as session:
        ref_result = await session.scalars(
            select(ResourceRef).where(
                ResourceRef.resource_id == dataset_id,
                ResourceRef.ref_name == "main",
            )
        )
        ref = ref_result.first()
        assert ref is not None
        assert ref.head_version_id == new_version_id

        version_result = await session.scalars(
            select(ResourceVersion).where(ResourceVersion.id == new_version_id)
        )
        version = version_result.first()
        assert version is not None
        assert set(version.parents) == {target_head_id, source_head_id}
        assert version.content["pipeline_refs"] == ["pipe:v2"]

        activity_result = await session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.resource_id == dataset_id,
                Activity.action.in_(
                    ["merge.requested", "merge.approved", "merge.executed"]
                ),
            )
        )
        actions = {activity.action for activity in activity_result.all()}
        assert {"merge.requested", "merge.approved", "merge.executed"} <= actions
