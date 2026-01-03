from __future__ import annotations

from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session, utcnow
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import EffectivePermissionsOut, RoleBindingCreate, RoleBindingOut
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac import authorize
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.identity import Principal
from libs.db.models.rbac import RoleBinding

router = APIRouter(prefix="/rbac", tags=["RBAC"])


@router.post(
    "/grants",
    response_model=RoleBindingOut,
    status_code=201,
)
async def grant_role(
    payload: RoleBindingCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Grant role",
                "value": {
                    "principal_id": "11111111-1111-1111-1111-111111111111",
                    "role_name": "viewer",
                    "scope_resource_id": "22222222-2222-2222-2222-222222222222",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> RoleBindingOut:
    scope_resource = await get_resource_or_404(
        db, actor.tenant_id, payload.scope_resource_id
    )
    await authorize_or_403(db, actor, Permission.RBAC_GRANT, scope_resource.id)
    scope_resource_id = scope_resource.id
    scope_resource_type = scope_resource.type

    principal_result = await db.scalars(
        select(Principal).where(
            Principal.id == payload.principal_id,
            Principal.tenant_id == actor.tenant_id,
        )
    )
    if not principal_result.first():
        raise HTTPException(status_code=404, detail="Principal not found in tenant")

    binding_id = uuid4()

    async def domain_fn(session: AsyncSession) -> RoleBinding:
        binding = RoleBinding(
            id=binding_id,
            tenant_id=actor.tenant_id,
            principal_id=payload.principal_id,
            scope_resource_id=payload.scope_resource_id,
            role_name=payload.role_name,
            granted_by=actor.id,
        )
        session.add(binding)
        await session.flush()
        return binding

    await reset_session(db)

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=scope_resource_id,
        resource_type=scope_resource_type,
        action="rbac.granted",
        payload={
            "principal_id": str(payload.principal_id),
            "role": payload.role_name,
            "scope_resource_id": str(payload.scope_resource_id),
        },
    )
    binding, _activity = await tx_activity(db, envelope, domain_fn)
    return RoleBindingOut.model_validate(binding)


@router.delete("/grants/{binding_id}", response_model=RoleBindingOut)
async def revoke_role(
    binding_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> RoleBindingOut:
    result = await db.scalars(
        select(RoleBinding).where(
            RoleBinding.id == binding_id,
            RoleBinding.tenant_id == actor.tenant_id,
        )
    )
    binding = result.first()
    if not binding:
        raise HTTPException(status_code=404, detail="Role binding not found")

    await authorize_or_403(db, actor, Permission.RBAC_REVOKE, binding.scope_resource_id)
    scope_resource_id = binding.scope_resource_id
    principal_id = binding.principal_id
    role_name = binding.role_name

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> RoleBinding:
        result = await session.scalars(
            select(RoleBinding).where(RoleBinding.id == binding_id)
        )
        target = result.first()
        if not target:
            raise HTTPException(status_code=404, detail="Role binding not found")
        target.revoked_at = utcnow()
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=scope_resource_id,
        resource_type="RBAC",
        action="rbac.revoked",
        payload={
            "principal_id": str(principal_id),
            "role": role_name,
            "scope_resource_id": str(scope_resource_id),
        },
    )
    revoked, _activity = await tx_activity(db, envelope, domain_fn)
    return RoleBindingOut.model_validate(revoked)


@router.get("/grants", response_model=List[RoleBindingOut])
async def list_grants(
    resource_id: UUID = Query(..., description="Scope resource to list bindings for"),
    principal_id: Optional[UUID] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[RoleBindingOut]:
    await authorize_or_403(db, actor, Permission.RBAC_VIEW, resource_id)

    query = select(RoleBinding).where(
        RoleBinding.tenant_id == actor.tenant_id,
        RoleBinding.scope_resource_id == resource_id,
        RoleBinding.revoked_at.is_(None),
    )
    if principal_id:
        query = query.where(RoleBinding.principal_id == principal_id)

    result = await db.scalars(query.order_by(RoleBinding.granted_at.desc()))
    return [RoleBindingOut.model_validate(binding) for binding in result.all()]


@router.get("/effective", response_model=EffectivePermissionsOut)
async def list_effective_permissions(
    resource_id: UUID = Query(..., description="Resource to evaluate"),
    principal_id: Optional[UUID] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> EffectivePermissionsOut:
    await authorize_or_403(db, actor, Permission.RBAC_VIEW, resource_id)

    subject_id = principal_id or actor.id
    principal = await db.scalars(
        select(Principal).where(
            Principal.id == subject_id,
            Principal.tenant_id == actor.tenant_id,
        )
    )
    if not principal.first():
        raise HTTPException(status_code=404, detail="Principal not found in tenant")

    allowed: List[str] = []
    for perm in Permission:
        is_allowed, _explain = await authorize(
            db, actor.tenant_id, subject_id, resource_id, perm
        )
        if is_allowed:
            allowed.append(perm.value)

    return EffectivePermissionsOut(
        principal_id=subject_id, resource_id=resource_id, permissions=allowed
    )
