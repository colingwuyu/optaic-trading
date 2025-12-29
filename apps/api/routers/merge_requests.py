from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    MergeApprovalIn,
    MergeApprovalOut,
    MergeExecuteOut,
    MergeRequestCreate,
    MergeRequestOut,
)
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac import authorize
from libs.core.rbac.models import ActorContext, Permission
from libs.core.versioning import (
    create_version,
    is_versioned_type,
    merge_content,
    update_ref,
)
from libs.db.models.merge import Approval, MergeRequest
from libs.db.models.resource import Resource, ResourceRef, ResourceVersion

router = APIRouter(prefix="/merge-requests", tags=["MergeRequests"])

_MR_OPEN_STATUSES = {"open", "approved"}


def _resource_channel(tenant_id: UUID, resource_id: UUID) -> str:
    return f"t:{tenant_id}:r:{resource_id}"


async def _get_merge_request(
    db: AsyncSession, tenant_id: UUID, mr_id: UUID
) -> MergeRequest:
    result = await db.scalars(
        select(MergeRequest).where(
            MergeRequest.id == mr_id,
            MergeRequest.tenant_id == tenant_id,
        )
    )
    mr = result.first()
    if not mr:
        raise HTTPException(status_code=404, detail="Merge request not found")
    return mr


async def _get_ref(
    db: AsyncSession, tenant_id: UUID, resource_id: UUID, ref_name: str
) -> ResourceRef:
    result = await db.scalars(
        select(ResourceRef).where(
            ResourceRef.tenant_id == tenant_id,
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == ref_name,
        )
    )
    ref = result.first()
    if not ref:
        raise HTTPException(status_code=404, detail="Ref not found")
    return ref


async def _count_approvals(
    db: AsyncSession, tenant_id: UUID, mr_resource_id: UUID
) -> tuple[int, int]:
    approve_count = await db.scalar(
        select(func.count(Approval.id)).where(
            Approval.tenant_id == tenant_id,
            Approval.resource_id == mr_resource_id,
            Approval.decision == "approve",
        )
    )
    reject_count = await db.scalar(
        select(func.count(Approval.id)).where(
            Approval.tenant_id == tenant_id,
            Approval.resource_id == mr_resource_id,
            Approval.decision == "reject",
        )
    )
    return int(approve_count or 0), int(reject_count or 0)


async def _authorize_on_target_or_mr(
    db: AsyncSession,
    actor: ActorContext,
    permission: Permission,
    target_resource_id: UUID,
    mr_resource_id: UUID,
) -> None:
    allowed, _explain = await authorize(
        db, actor.tenant_id, actor.id, target_resource_id, permission
    )
    if allowed:
        return
    allowed, _explain = await authorize(
        db, actor.tenant_id, actor.id, mr_resource_id, permission
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("", response_model=MergeRequestOut, status_code=201)
async def create_merge_request(
    payload: MergeRequestCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create merge request",
                "value": {
                    "target_resource_id": "11111111-1111-1111-1111-111111111111",
                    "source_ref": "feature-x",
                    "target_ref": "main",
                    "title": "Add metric",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MergeRequestOut:
    target_resource = await get_resource_or_404(
        db, actor.tenant_id, payload.target_resource_id
    )
    if not is_versioned_type(target_resource.type):
        raise HTTPException(status_code=400, detail="Target resource is not versioned")
    await authorize_or_403(db, actor, Permission.MERGE_REQUEST_CREATE, target_resource.id)
    target_resource_id = target_resource.id
    target_resource_type = target_resource.type

    source_ref = await _get_ref(
        db, actor.tenant_id, target_resource_id, payload.source_ref
    )
    target_ref = await _get_ref(
        db, actor.tenant_id, target_resource_id, payload.target_ref
    )

    source_head_id = source_ref.head_version_id
    target_head_id = target_ref.head_version_id
    source_head = await db.scalars(
        select(ResourceVersion).where(ResourceVersion.id == source_head_id)
    )
    source_version = source_head.first()
    target_head = await db.scalars(
        select(ResourceVersion).where(ResourceVersion.id == target_head_id)
    )
    target_version = target_head.first()
    if not source_version or not target_version:
        raise HTTPException(status_code=400, detail="Missing ref head versions")

    mr_id = uuid4()
    mr_resource_id = uuid4()
    required_approvals = payload.required_approvals

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> MergeRequest:
        resource_name = payload.title or f"Merge {payload.source_ref} into {payload.target_ref}"
        mr_resource = Resource(
            id=mr_resource_id,
            tenant_id=actor.tenant_id,
            type="MergeRequest",
            parent_id=target_resource_id,
            owner_principal_id=actor.id,
            name=resource_name,
            status="active",
            metadata_json={
                "target_resource_id": str(target_resource_id),
                "source_ref": payload.source_ref,
                "target_ref": payload.target_ref,
            },
        )
        session.add(mr_resource)
        await session.flush()

        mr = MergeRequest(
            id=mr_id,
            tenant_id=actor.tenant_id,
            mr_resource_id=mr_resource_id,
            target_resource_id=target_resource_id,
            source_ref=payload.source_ref,
            target_ref=payload.target_ref,
            status="open",
            required_approvals=required_approvals,
            title=payload.title,
            description=payload.description,
            created_by=actor.id,
        )
        session.add(mr)
        await session.flush()
        return mr

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=target_resource_id,
        resource_type=target_resource_type,
        action="merge.requested",
        payload={
            "mr_id": str(mr_id),
            "target_resource_id": str(target_resource_id),
            "source_ref": payload.source_ref,
            "target_ref": payload.target_ref,
            "source_head": str(source_head_id),
            "target_head": str(target_head_id),
        },
        delivery_channels=[_resource_channel(actor.tenant_id, target_resource_id)],
    )
    mr, _activity = await tx_activity(db, envelope, domain_fn)
    return MergeRequestOut.model_validate(mr)


@router.get("/{mr_id}", response_model=MergeRequestOut)
async def get_merge_request(
    mr_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MergeRequestOut:
    mr = await _get_merge_request(db, actor.tenant_id, mr_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, mr.target_resource_id)
    return MergeRequestOut.model_validate(mr)


@router.post("/{mr_id}/approve", response_model=MergeApprovalOut)
async def approve_merge_request(
    mr_id: UUID,
    payload: MergeApprovalIn = Body(
        ...,
        examples={
            "default": {
                "summary": "Approve merge request",
                "value": {"decision": "approve", "comment": "LGTM"},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MergeApprovalOut:
    mr = await _get_merge_request(db, actor.tenant_id, mr_id)
    target_resource = await get_resource_or_404(db, actor.tenant_id, mr.target_resource_id)
    target_resource_type = target_resource.type
    target_resource_id = target_resource.id
    mr_resource_id = mr.mr_resource_id
    required_approvals = mr.required_approvals
    mr_record_id = mr.id
    await _authorize_on_target_or_mr(
        db, actor, Permission.MERGE_APPROVE, mr.target_resource_id, mr.mr_resource_id
    )

    if mr.status in {"merged", "closed"}:
        raise HTTPException(status_code=409, detail="Merge request is closed")

    decision = payload.decision.lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Invalid decision")

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Approval:
        stmt = (
            pg_insert(Approval)
            .values(
                tenant_id=actor.tenant_id,
                resource_id=mr_resource_id,
                approver_id=actor.id,
                decision=decision,
                comment=payload.comment,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "resource_id", "approver_id"],
                set_={
                    "decision": decision,
                    "comment": payload.comment,
                },
            )
            .returning(Approval)
        )
        result = await session.execute(stmt)
        approval = result.scalar_one()

        mr_row_result = await session.scalars(
            select(MergeRequest).where(
                MergeRequest.id == mr_record_id,
                MergeRequest.tenant_id == actor.tenant_id,
            )
        )
        mr_row = mr_row_result.first()
        if not mr_row:
            raise HTTPException(status_code=404, detail="Merge request not found")

        approvals, rejects = await _count_approvals(
            session, actor.tenant_id, mr_resource_id
        )
        envelope.payload["counts"] = {
            "approvals": approvals,
            "rejects": rejects,
            "required": required_approvals,
        }
        if rejects > 0:
            mr_row.status = "rejected"
        elif approvals >= required_approvals:
            mr_row.status = "approved"
        else:
            mr_row.status = "open"
        await session.flush()
        return approval

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=target_resource_id,
        resource_type=target_resource_type,
        action="merge.approved",
        payload={
            "mr_id": str(mr_record_id),
            "decision": decision,
            "approver": str(actor.id),
            "counts": {},
        },
        delivery_channels=[_resource_channel(actor.tenant_id, target_resource_id)],
    )
    _approval, _activity = await tx_activity(db, envelope, domain_fn)

    updated_mr = await _get_merge_request(db, actor.tenant_id, mr_record_id)
    approvals_after, rejects_after = await _count_approvals(
        db, actor.tenant_id, mr_resource_id
    )
    return MergeApprovalOut(
        mr_id=mr_record_id,
        decision=decision,
        approvals=approvals_after,
        rejects=rejects_after,
        required_approvals=required_approvals,
        status=updated_mr.status,
    )


@router.post("/{mr_id}/merge", response_model=MergeExecuteOut)
async def merge_merge_request(
    mr_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MergeExecuteOut:
    mr = await _get_merge_request(db, actor.tenant_id, mr_id)
    mr_record_id = mr.id
    target_resource_id = mr.target_resource_id
    target_ref_name = mr.target_ref
    source_ref_name = mr.source_ref
    mr_resource_id = mr.mr_resource_id
    await _authorize_on_target_or_mr(
        db, actor, Permission.MERGE_EXECUTE, mr.target_resource_id, mr.mr_resource_id
    )
    if mr.status == "merged":
        raise HTTPException(status_code=409, detail="Merge request already merged")

    approvals, rejects = await _count_approvals(db, actor.tenant_id, mr_resource_id)
    if rejects > 0 or approvals < mr.required_approvals:
        raise HTTPException(status_code=400, detail="Merge request not approved")

    target_resource = await get_resource_or_404(
        db, actor.tenant_id, target_resource_id
    )
    if not is_versioned_type(target_resource.type):
        raise HTTPException(status_code=400, detail="Target resource is not versioned")
    target_resource_type = target_resource.type

    source_ref = await _get_ref(db, actor.tenant_id, target_resource_id, source_ref_name)
    target_ref = await _get_ref(db, actor.tenant_id, target_resource_id, target_ref_name)

    source_head = await db.scalars(
        select(ResourceVersion).where(ResourceVersion.id == source_ref.head_version_id)
    )
    source_version = source_head.first()
    target_head = await db.scalars(
        select(ResourceVersion).where(ResourceVersion.id == target_ref.head_version_id)
    )
    target_version = target_head.first()
    if not source_version or not target_version:
        raise HTTPException(status_code=400, detail="Missing ref head versions")
    source_version_id = source_version.id
    target_version_id = target_version.id

    merged_content = merge_content(
        target_resource_type,
        target_version.content or {},
        source_version.content or {},
    )

    new_version_id = uuid4()

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> ResourceVersion:
        new_version = await create_version(
            session,
            target_resource_id,
            parents=[target_version_id, source_version_id],
            content=merged_content,
            created_by=actor.id,
            version_id=new_version_id,
        )
        await update_ref(
            session,
            target_resource_id,
            target_ref_name,
            new_version.id,
            actor.id,
        )
        mr_row_result = await session.scalars(
            select(MergeRequest).where(
                MergeRequest.id == mr_record_id,
                MergeRequest.tenant_id == actor.tenant_id,
            )
        )
        mr_row = mr_row_result.first()
        if not mr_row:
            raise HTTPException(status_code=404, detail="Merge request not found")
        mr_row.status = "merged"
        await session.flush()
        return new_version

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=target_resource_id,
        resource_type=target_resource_type,
        action="merge.executed",
        payload={
            "mr_id": str(mr_record_id),
            "new_version_id": str(new_version_id),
        },
        delivery_channels=[_resource_channel(actor.tenant_id, target_resource_id)],
    )
    new_version, _activity = await tx_activity(db, envelope, domain_fn)

    if new_version is None:
        raise HTTPException(status_code=409, detail="Merge execution already recorded")

    return MergeExecuteOut(
        mr_id=mr_record_id,
        target_resource_id=target_resource_id,
        target_ref=target_ref_name,
        new_version_id=new_version.id,
        status="merged",
    )
