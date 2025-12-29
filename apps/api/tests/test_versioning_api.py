import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.main import app
from libs.db.models.resource import ResourceRef, ResourceVersion
from libs.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_create_dataset_creates_main_ref_and_version():
    owner_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Versioned Tenant"},
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
                "name": "Dataset One",
            },
        )
        assert dataset_response.status_code == 201
        dataset_id = uuid.UUID(dataset_response.json()["id"])

    async with AsyncSessionLocal() as session:
        ref_result = await session.scalars(
            select(ResourceRef).where(
                ResourceRef.resource_id == dataset_id,
                ResourceRef.ref_name == "main",
            )
        )
        ref = ref_result.first()
        assert ref is not None

        version_result = await session.scalars(
            select(ResourceVersion).where(ResourceVersion.id == ref.head_version_id)
        )
        version = version_result.first()
        assert version is not None
        assert version.parents == []
        assert version.content is not None
        assert set(version.content.keys()) == {
            "pipeline_refs",
            "store_refs",
            "accessor_refs",
            "config",
        }
