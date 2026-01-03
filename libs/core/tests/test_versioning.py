import uuid

import pytest
from sqlalchemy import insert, select

from libs.core.versioning import (
    create_version,
    get_current_head,
    initialize_versioning,
    update_ref,
)
from libs.db.models.identity import Principal, Tenant
from libs.db.models.resource import Resource, ResourceRef, ResourceVersion
from libs.db.session import AsyncSessionLocal


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def _seed_tenant_and_principal(db, tenant_id, principal_id):
    await db.execute(insert(Tenant).values(id=tenant_id, name=f"T-{tenant_id.hex[:4]}"))
    await db.execute(
        insert(Principal).values(
            id=principal_id,
            tenant_id=tenant_id,
            kind="user",
            status="active",
            display_name=f"P-{principal_id.hex[:4]}",
        )
    )


@pytest.mark.asyncio
async def test_version_chain_updates_head(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)
    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Dataset",
            owner_principal_id=actor_id,
            name="Dataset",
        )
    )

    result = await db_session.scalars(
        select(Resource).where(Resource.id == resource_id)
    )
    resource = result.first()
    assert resource is not None

    initial_version = await initialize_versioning(db_session, resource, actor_id)
    assert initial_version is not None

    head = await get_current_head(db_session, resource_id)
    assert head is not None
    assert head.id == initial_version.id

    next_version = await create_version(
        db_session,
        resource_id,
        parents=[head.id],
        content={
            "pipeline_refs": ["pipe:v2"],
            "store_refs": [],
            "accessor_refs": [],
            "config": {"v": 2},
        },
        created_by=actor_id,
    )
    await update_ref(db_session, resource_id, "main", next_version.id, actor_id)

    head_after = await get_current_head(db_session, resource_id)
    assert head_after is not None
    assert head_after.id == next_version.id
    assert head_after.parents == [head.id]


@pytest.mark.asyncio
async def test_initialize_creates_main_ref(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)
    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Dataset",
            owner_principal_id=actor_id,
            name="Dataset",
        )
    )

    result = await db_session.scalars(
        select(Resource).where(Resource.id == resource_id)
    )
    resource = result.first()
    assert resource is not None

    initial_version = await initialize_versioning(db_session, resource, actor_id)
    assert initial_version is not None

    ref_result = await db_session.scalars(
        select(ResourceRef).where(
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == "main",
        )
    )
    ref = ref_result.first()
    assert ref is not None
    assert ref.head_version_id == initial_version.id

    version_result = await db_session.scalars(
        select(ResourceVersion).where(ResourceVersion.id == initial_version.id)
    )
    version = version_result.first()
    assert version is not None
    assert version.parents == []
