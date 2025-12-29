from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import BranchCreate, BranchOut
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.core.versioning import is_versioned_type
from libs.db.models.merge import MergeRequest
from libs.db.models.resource import ResourceRef

router = APIRouter(prefix="/refs", tags=["Refs"])
_MR_OPEN_STATUSES = {"open", "approved"}


def _resource_channel(tenant_id: UUID, resource_id: UUID) -> str:
    return f"t:{tenant_id}:r:{resource_id}"


def _has_open_merge_requests(metadata: dict, ref_name: str) -> bool:
    open_refs = metadata.get("open_merge_refs", [])
    return isinstance(open_refs, list) and ref_name in open_refs


async def _has_open_merge_requests_in_db(
    db: AsyncSession, tenant_id: UUID, resource_id: UUID, ref_name: str
) -> bool:
    result = await db.scalars(
        select(MergeRequest.id).where(
            MergeRequest.tenant_id == tenant_id,
            MergeRequest.target_resource_id == resource_id,
            MergeRequest.status.in_(_MR_OPEN_STATUSES),
            (MergeRequest.source_ref == ref_name) | (MergeRequest.target_ref == ref_name),
        )
    )
    return result.first() is not None


@router.post(
    "/{resource_id}/branches",
    response_model=BranchOut,
    status_code=201,
)
async def create_branch(
    resource_id: UUID,
    payload: BranchCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create branch",
                "value": {"ref_name": "feature-x", "from_ref": "main"},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BranchOut:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    if not is_versioned_type(resource.type):
        raise HTTPException(status_code=400, detail="Resource type is not versioned")
    await authorize_or_403(db, actor, Permission.BRANCH_CREATE, resource_id)
    resource_type = resource.type

    existing_ref = await db.scalars(
        select(ResourceRef).where(
            ResourceRef.tenant_id == actor.tenant_id,
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == payload.ref_name,
        )
    )
    if existing_ref.first():
        raise HTTPException(status_code=409, detail="Branch already exists")

    from_ref_result = await db.scalars(
        select(ResourceRef).where(
            ResourceRef.tenant_id == actor.tenant_id,
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == payload.from_ref,
        )
    )
    from_ref = from_ref_result.first()
    if not from_ref:
        raise HTTPException(status_code=404, detail="Source ref not found")
    from_version_id = from_ref.head_version_id

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> ResourceRef:
        ref = ResourceRef(
            tenant_id=actor.tenant_id,
            resource_id=resource_id,
            ref_name=payload.ref_name,
            head_version_id=from_version_id,
            updated_by=actor.id,
        )
        session.add(ref)
        await session.flush()
        return ref

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="branch.created",
        payload={
            "resource_id": str(resource_id),
            "ref_name": payload.ref_name,
            "from_ref": payload.from_ref,
            "from_version_id": str(from_version_id),
        },
        delivery_channels=[_resource_channel(actor.tenant_id, resource_id)],
    )
    ref, _activity = await tx_activity(db, envelope, domain_fn)
    return BranchOut.model_validate(ref)


@router.get("/{resource_id}/branches", response_model=List[BranchOut])
async def list_branches(
    resource_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[BranchOut]:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    if not is_versioned_type(resource.type):
        raise HTTPException(status_code=400, detail="Resource type is not versioned")
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource_id)

    result = await db.scalars(
        select(ResourceRef)
        .where(
            ResourceRef.tenant_id == actor.tenant_id,
            ResourceRef.resource_id == resource_id,
        )
        .order_by(ResourceRef.ref_name.asc())
    )
    return [BranchOut.model_validate(ref) for ref in result.all()]


@router.delete("/{resource_id}/branches/{ref_name}", response_model=BranchOut)
async def delete_branch(
    resource_id: UUID,
    ref_name: str,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BranchOut:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    if not is_versioned_type(resource.type):
        raise HTTPException(status_code=400, detail="Resource type is not versioned")
    await authorize_or_403(db, actor, Permission.BRANCH_CREATE, resource_id)
    resource_type = resource.type

    if ref_name == "main":
        raise HTTPException(status_code=400, detail="Cannot delete main ref")
    if _has_open_merge_requests(resource.metadata_json or {}, ref_name):
        raise HTTPException(status_code=409, detail="Branch has open merge requests")
    if await _has_open_merge_requests_in_db(db, actor.tenant_id, resource_id, ref_name):
        raise HTTPException(status_code=409, detail="Branch has open merge requests")

    ref_result = await db.scalars(
        select(ResourceRef).where(
            ResourceRef.tenant_id == actor.tenant_id,
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == ref_name,
        )
    )
    ref = ref_result.first()
    if not ref:
        raise HTTPException(status_code=404, detail="Branch not found")

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> ResourceRef:
        target_result = await session.scalars(
            select(ResourceRef).where(
                ResourceRef.tenant_id == actor.tenant_id,
                ResourceRef.resource_id == resource_id,
                ResourceRef.ref_name == ref_name,
            )
        )
        target = target_result.first()
        if not target:
            raise HTTPException(status_code=404, detail="Branch not found")
        await session.delete(target)
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="branch.deleted",
        payload={"resource_id": str(resource_id), "ref_name": ref_name},
        delivery_channels=[_resource_channel(actor.tenant_id, resource_id)],
    )
    deleted, _activity = await tx_activity(db, envelope, domain_fn)
    return BranchOut.model_validate(deleted)
