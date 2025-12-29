from __future__ import annotations

from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session
from apps.api.rbac_utils import authorize_or_403
from apps.api.schemas import PrincipalCreate, PrincipalOut
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.identity import Principal
from libs.db.models.resource import Resource

router = APIRouter(prefix="/principals", tags=["Principals"])

async def _get_tenant_root(db: AsyncSession, tenant_id: UUID) -> Resource:
    result = await db.scalars(
        select(Resource)
        .where(
            Resource.tenant_id == tenant_id,
            Resource.type == "TenantRoot",
        )
        .order_by(Resource.created_at)
    )
    root = result.first()
    if not root:
        raise HTTPException(status_code=404, detail="Tenant root resource not found")
    return root

@router.post("", response_model=PrincipalOut, status_code=201)
async def create_principal(
    payload: PrincipalCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create principal",
                "value": {"display_name": "Dev User", "email": "dev@example.com"},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PrincipalOut:
    root = await _get_tenant_root(db, actor.tenant_id)
    await authorize_or_403(db, actor, Permission.INVITE_CREATE, root.id)

    root_id = root.id
    root_type = root.type
    principal_id = payload.id or uuid4()

    existing = await db.scalars(select(Principal).where(Principal.id == principal_id))
    if existing.first():
        raise HTTPException(status_code=409, detail="Principal already exists")

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Principal:
        principal = Principal(
            id=principal_id,
            tenant_id=actor.tenant_id,
            kind=payload.kind,
            status=payload.status,
            display_name=payload.display_name,
            email=payload.email,
        )
        session.add(principal)
        await session.flush()
        return principal

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=root_id,
        resource_type=root_type,
        action="principal.created",
        target_principal_id=principal_id,
        payload={"principal_id": str(principal_id), "display_name": payload.display_name},
    )
    created, _activity = await tx_activity(db, envelope, domain_fn)
    return PrincipalOut.model_validate(created)

@router.get("", response_model=List[PrincipalOut])
async def list_principals(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[PrincipalOut]:
    root = await _get_tenant_root(db, actor.tenant_id)
    await authorize_or_403(db, actor, Permission.RBAC_VIEW, root.id)

    result = await db.scalars(
        select(Principal)
        .where(Principal.tenant_id == actor.tenant_id)
        .order_by(Principal.created_at)
    )
    principals = result.all()
    return [PrincipalOut.model_validate(principal) for principal in principals]
