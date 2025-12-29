import pytest
import uuid
from sqlalchemy import insert
from libs.db.models.identity import Tenant, Principal
from libs.db.models.resource import Resource
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.core.rbac import authorize, Permission
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
async def test_authorize_enforces_tenant_isolation(db_session):
    tenant_resource = uuid.uuid4()
    tenant_actor = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    resource_owner_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_resource, resource_owner_id)
    await _seed_tenant_and_principal(db_session, tenant_actor, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_resource,
            type="Space",
            owner_principal_id=resource_owner_id,
            name="TenantResource",
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_resource,
            role_name="viewer",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_resource,
            principal_id=actor_id,
            scope_resource_id=resource_id,
            role_name="viewer",
            granted_by=actor_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_actor,
        actor_id,
        resource_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is False
    assert explain["details"]["reason"] == "tenant_mismatch"
    assert explain["details"]["checked_scopes"] == [str(resource_id)]
    assert explain["details"]["binding"] is None

@pytest.mark.asyncio
async def test_authorize_inherits_from_parent_scope(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=parent_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Parent",
        )
    )

    await db_session.execute(
        insert(Resource).values(
            id=child_id,
            tenant_id=tenant_id,
            type="Project",
            parent_id=parent_id,
            owner_principal_id=actor_id,
            name="Child",
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_id,
            role_name="owner",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            scope_resource_id=parent_id,
            role_name="owner",
            granted_by=actor_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_id,
        actor_id,
        child_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is True
    assert explain["scope_resource_id"] == str(parent_id)
    assert explain["inherited"] is True
    assert explain["details"]["checked_scopes"] == [str(child_id), str(parent_id)]
    assert explain["details"]["binding"]["id"] is not None
    assert (
        explain["details"]["permission"]["name"]
        == Permission.RESOURCE_READ.value
    )

@pytest.mark.asyncio
async def test_authorize_child_override_with_break(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=parent_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Parent",
        )
    )

    await db_session.execute(
        insert(Resource).values(
            id=child_id,
            tenant_id=tenant_id,
            type="Project",
            parent_id=parent_id,
            owner_principal_id=actor_id,
            name="Child",
            metadata_json={"inherit_break": True},
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_id,
            role_name="viewer",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            scope_resource_id=parent_id,
            role_name="viewer",
            granted_by=actor_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_id,
        actor_id,
        child_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is False
    assert explain["details"]["reason"] == "binding_not_found"
    assert explain["details"]["checked_scopes"] == [str(child_id)]

@pytest.mark.asyncio
async def test_authorize_denies_when_no_binding(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Solo",
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_id,
            role_name="viewer",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_id,
        actor_id,
        resource_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is False
    assert explain["details"]["reason"] == "binding_not_found"


@pytest.mark.asyncio
async def test_authorize_respects_resource_type_policies(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=parent_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Parent",
        )
    )

    await db_session.execute(
        insert(Resource).values(
            id=child_id,
            tenant_id=tenant_id,
            type="Project",
            parent_id=parent_id,
            owner_principal_id=actor_id,
            name="Child",
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_id,
            role_name="viewer",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            scope_resource_id=child_id,
            role_name="viewer",
            granted_by=actor_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_id,
        actor_id,
        child_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is False
    assert explain["details"]["reason"] == "binding_not_found"

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            scope_resource_id=parent_id,
            role_name="viewer",
            granted_by=actor_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_id,
        actor_id,
        child_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is True
    assert explain["scope_resource_id"] == str(parent_id)
    assert explain["details"]["permission"]["resource_type"] == "Space"


@pytest.mark.asyncio
async def test_authorize_tenant_isolation_rejects_cross_tenant_binding(db_session):
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, owner_id)
    await _seed_tenant_and_principal(db_session, other_tenant_id, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=owner_id,
            name="TenantResource",
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_id,
            role_name="viewer",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            scope_resource_id=resource_id,
            role_name="viewer",
            granted_by=owner_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        other_tenant_id,
        actor_id,
        resource_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is False
    assert explain["details"]["reason"] == "tenant_mismatch"


@pytest.mark.asyncio
async def test_authorize_inherit_break_blocks_grandparent(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    grandparent_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    await _seed_tenant_and_principal(db_session, tenant_id, actor_id)

    await db_session.execute(
        insert(Resource).values(
            id=grandparent_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Grandparent",
        )
    )

    await db_session.execute(
        insert(Resource).values(
            id=parent_id,
            tenant_id=tenant_id,
            type="Project",
            parent_id=grandparent_id,
            owner_principal_id=actor_id,
            name="Parent",
            metadata_json={"inherit_break": True},
        )
    )

    await db_session.execute(
        insert(Resource).values(
            id=child_id,
            tenant_id=tenant_id,
            type="Task",
            parent_id=parent_id,
            owner_principal_id=actor_id,
            name="Child",
        )
    )

    await db_session.execute(
        insert(RolePermission).values(
            tenant_id=tenant_id,
            role_name="viewer",
            perm_name=Permission.RESOURCE_READ.value,
            resource_type="Space",
        )
    )

    await db_session.execute(
        insert(RoleBinding).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            principal_id=actor_id,
            scope_resource_id=grandparent_id,
            role_name="viewer",
            granted_by=actor_id,
        )
    )

    allowed, explain = await authorize(
        db_session,
        tenant_id,
        actor_id,
        child_id,
        Permission.RESOURCE_READ,
    )

    assert allowed is False
    assert explain["details"]["reason"] == "binding_not_found"
    assert explain["details"]["checked_scopes"] == [str(child_id), str(parent_id)]
