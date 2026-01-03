from __future__ import annotations

from typing import List
from uuid import uuid4, UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import (
    get_actor,
    get_db,
    get_principal_id,
    get_tenant_id,
    reset_session,
)
from apps.api.schemas import TenantCreate, TenantOut
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac import authorize
from libs.core.rbac.models import ActorContext, Permission, GLOBAL_RESOURCE_TYPE
from libs.db.models.identity import Tenant, Principal
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.db.models.resource import Resource

router = APIRouter(prefix="/tenants", tags=["Tenants"])

DEFAULT_ROLE_PERMISSIONS = {
    "owner": [perm.value for perm in Permission],
    "operator": [
        Permission.CHANNEL_VIEW_HISTORY.value,
        Permission.CHANNEL_POST.value,
        Permission.CHANNEL_EDIT_OWN.value,
        Permission.CHANNEL_DELETE_OWN.value,
    ],
    "viewer": [
        Permission.RESOURCE_READ.value,
        Permission.VIEW_ACTIVITY_FEED.value,
    ],
    "auditor": [Permission.VIEW_ACTIVITY_FEED.value],
}


@router.post(
    "",
    response_model=TenantOut,
    status_code=201,
)
async def create_tenant(
    payload: TenantCreate = Body(
        ...,
        examples={
            "default": {"summary": "Create tenant", "value": {"name": "Acme Corp"}}
        },
    ),
    principal_id: UUID = Depends(get_principal_id),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TenantOut:
    existing_principal = await db.scalars(
        select(Principal).where(Principal.id == principal_id)
    )
    if existing_principal.first():
        raise HTTPException(status_code=409, detail="Principal already exists")

    existing_tenant = await db.scalars(select(Tenant).where(Tenant.id == tenant_id))
    if existing_tenant.first():
        raise HTTPException(status_code=409, detail="Tenant already exists")

    root_resource_id = uuid4()

    async def domain_fn(session: AsyncSession) -> tuple[Tenant, Resource]:
        tenant = Tenant(id=tenant_id, name=payload.name)
        session.add(tenant)
        await session.flush()

        principal = Principal(
            id=principal_id,
            tenant_id=tenant_id,
            kind="user",
            status="active",
            display_name=f"dev-{principal_id.hex[:6]}",
        )
        root_resource = Resource(
            id=root_resource_id,
            tenant_id=tenant_id,
            type="TenantRoot",
            parent_id=None,
            owner_principal_id=principal_id,
            name=f"{payload.name} Root",
            status="active",
            metadata_json={"root": True},
        )
        session.add_all([principal, root_resource])
        await session.flush()

        role_rows = []
        for role_name, perms in DEFAULT_ROLE_PERMISSIONS.items():
            for perm_name in perms:
                role_rows.append(
                    {
                        "tenant_id": tenant_id,
                        "resource_type": GLOBAL_RESOURCE_TYPE,
                        "role_name": role_name,
                        "perm_name": perm_name,
                    }
                )
        if role_rows:
            stmt = pg_insert(RolePermission).values(role_rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["tenant_id", "resource_type", "role_name", "perm_name"]
            )
            await session.execute(stmt)

        owner_binding = RoleBinding(
            tenant_id=tenant_id,
            principal_id=principal_id,
            scope_resource_id=root_resource_id,
            role_name="owner",
            granted_by=principal_id,
        )
        session.add(owner_binding)
        await session.flush()

        allowed, _explain = await authorize(
            session, tenant_id, principal_id, root_resource_id, Permission.RBAC_GRANT
        )
        if not allowed:
            raise HTTPException(
                status_code=403, detail="Bootstrap authorization failed"
            )

        return tenant, root_resource

    await reset_session(db)

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=principal_id,
        resource_id=root_resource_id,
        resource_type="TenantRoot",
        action="tenant.created",
        payload={
            "tenant_id": str(tenant_id),
            "root_resource_id": str(root_resource_id),
        },
    )
    (tenant, _root_resource), _activity = await tx_activity(db, envelope, domain_fn)
    return TenantOut(
        id=tenant.id,
        name=tenant.name,
        created_at=tenant.created_at,
        root_resource_id=root_resource_id,
    )


@router.get("", response_model=List[TenantOut])
async def list_tenants(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[TenantOut]:
    result = await db.scalars(
        select(Tenant).where(Tenant.id == actor.tenant_id).order_by(Tenant.created_at)
    )
    tenants = result.all()
    return [TenantOut(id=t.id, name=t.name, created_at=t.created_at) for t in tenants]
