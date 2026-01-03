import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.main import app
from libs.db.models.activity import Activity
from libs.db.models.resource import Resource, ResourceEdge
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_promotion_move_requires_destination_owner_and_updates_parent():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Promotion Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        source_space = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Space", "parent_id": root_resource_id, "name": "Source"},
        )
        assert source_space.status_code == 201
        source_space_id = source_space.json()["id"]

        project_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Project", "parent_id": source_space_id, "name": "Project"},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        dest_space = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Space",
                "parent_id": root_resource_id,
                "name": "Destination",
            },
        )
        assert dest_space.status_code == 201
        dest_space_id = dest_space.json()["id"]

        approver_id = uuid.uuid4()
        principal_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"id": str(approver_id), "display_name": "Approver"},
        )
        assert principal_response.status_code == 201

        promotion_response = await client.post(
            "/promotions",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "moving_resource_id": project_id,
                "to_scope_id": dest_space_id,
                "placement": {"target": "dest"},
                "mode": "move",
            },
        )
        assert promotion_response.status_code == 201
        promotion_payload = promotion_response.json()
        pr_id = promotion_payload["id"]
        pr_resource_id = promotion_payload["pr_resource_id"]

        approve_forbidden = await client.post(
            f"/promotions/{pr_id}/approve",
            headers={"X-Principal-Id": str(approver_id), "X-Tenant-Id": str(tenant_id)},
            json={"decision": "approve"},
        )
        assert approve_forbidden.status_code == 403

        grant_response = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(approver_id),
                "role_name": "owner",
                "scope_resource_id": dest_space_id,
            },
        )
        assert grant_response.status_code == 201

        approve_response = await client.post(
            f"/promotions/{pr_id}/approve",
            headers={"X-Principal-Id": str(approver_id), "X-Tenant-Id": str(tenant_id)},
            json={"decision": "approve"},
        )
        assert approve_response.status_code == 200

        execute_response = await client.post(
            f"/promotions/{pr_id}/execute",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert execute_response.status_code == 200
        assert execute_response.json()["moved_count"] >= 1

    async with AsyncSessionLocal() as session:
        project_result = await session.scalars(
            select(Resource).where(Resource.id == uuid.UUID(project_id))
        )
        project = project_result.first()
        assert project is not None
        assert project.parent_id == uuid.UUID(dest_space_id)

        activity_result = await session.scalars(
            select(Activity).where(
                Activity.resource_id == uuid.UUID(pr_resource_id),
                Activity.action.in_(
                    ["promote.requested", "promote.approved", "promote.executed"]
                ),
            )
        )
        actions = {activity.action for activity in activity_result.all()}
        assert {"promote.requested", "promote.approved", "promote.executed"} <= actions


@pytest.mark.asyncio
async def test_promotion_copy_creates_derived_edge_and_reject_blocks_execute():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Copy Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        source_space = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Space", "parent_id": root_resource_id, "name": "Source"},
        )
        assert source_space.status_code == 201
        source_space_id = source_space.json()["id"]

        project_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Project", "parent_id": source_space_id, "name": "Project"},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        dataset_response = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"type": "Dataset", "parent_id": project_id, "name": "Dataset"},
        )
        assert dataset_response.status_code == 201

        dest_space = await client.post(
            "/resources",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "type": "Space",
                "parent_id": root_resource_id,
                "name": "Destination",
            },
        )
        assert dest_space.status_code == 201
        dest_space_id = dest_space.json()["id"]

        promotion_response = await client.post(
            "/promotions",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "moving_resource_id": project_id,
                "to_scope_id": dest_space_id,
                "placement": {"target": "dest"},
                "mode": "copy",
            },
        )
        assert promotion_response.status_code == 201
        promotion_payload = promotion_response.json()
        pr_id = promotion_payload["id"]

        approve_response = await client.post(
            f"/promotions/{pr_id}/approve",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"decision": "approve"},
        )
        assert approve_response.status_code == 200

        execute_response = await client.post(
            f"/promotions/{pr_id}/execute",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert execute_response.status_code == 200
        execution_payload = execute_response.json()
        new_root_id = uuid.UUID(execution_payload["new_root_id"])
        assert new_root_id != uuid.UUID(project_id)
        assert execution_payload["copied_count"] >= 2

        reject_promotion = await client.post(
            "/promotions",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "moving_resource_id": project_id,
                "to_scope_id": dest_space_id,
                "placement": {"target": "dest"},
                "mode": "move",
            },
        )
        assert reject_promotion.status_code == 201
        reject_pr_id = reject_promotion.json()["id"]

        reject_response = await client.post(
            f"/promotions/{reject_pr_id}/approve",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"decision": "reject"},
        )
        assert reject_response.status_code == 200

        reject_execute = await client.post(
            f"/promotions/{reject_pr_id}/execute",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert reject_execute.status_code == 400

    async with AsyncSessionLocal() as session:
        new_root_result = await session.scalars(
            select(Resource).where(Resource.id == new_root_id)
        )
        new_root = new_root_result.first()
        assert new_root is not None
        assert new_root.parent_id == uuid.UUID(dest_space_id)

        edge_result = await session.scalars(
            select(ResourceEdge).where(
                ResourceEdge.src_resource_id == new_root_id,
                ResourceEdge.dst_resource_id == uuid.UUID(project_id),
                ResourceEdge.edge_type == "derived_from",
            )
        )
        assert edge_result.first() is not None
