from __future__ import annotations

from typing import Dict, Iterable, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    PromotionApprovalIn,
    PromotionApprovalOut,
    PromotionCreate,
    PromotionExecuteOut,
    PromotionRequestOut,
)
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.core.versioning import initialize_versioning
from libs.db.models.merge import Approval
from libs.db.models.promotion import PromotionRequest, RbacTemplate
from libs.db.models.rbac import RoleBinding
from libs.db.models.resource import Resource, ResourceEdge

router = APIRouter(prefix="/promotions", tags=["Promotions"])

_OWNER_ROLES = {"owner", "delegator"}


def _resource_channel(tenant_id: UUID, resource_id: UUID) -> str:
    return f"t:{tenant_id}:r:{resource_id}"


async def _get_promotion_request(
    db: AsyncSession, tenant_id: UUID, pr_id: UUID
) -> PromotionRequest:
    result = await db.scalars(
        select(PromotionRequest).where(
            PromotionRequest.id == pr_id,
            PromotionRequest.tenant_id == tenant_id,
        )
    )
    pr = result.first()
    if not pr:
        raise HTTPException(status_code=404, detail="Promotion request not found")
    return pr


async def _count_approvals(
    db: AsyncSession, tenant_id: UUID, pr_resource_id: UUID
) -> tuple[int, int]:
    approve_count = await db.scalar(
        select(func.count(Approval.id)).where(
            Approval.tenant_id == tenant_id,
            Approval.resource_id == pr_resource_id,
            Approval.decision == "approve",
        )
    )
    reject_count = await db.scalar(
        select(func.count(Approval.id)).where(
            Approval.tenant_id == tenant_id,
            Approval.resource_id == pr_resource_id,
            Approval.decision == "reject",
        )
    )
    return int(approve_count or 0), int(reject_count or 0)


async def _scope_chain(
    db: AsyncSession, tenant_id: UUID, scope_id: UUID
) -> list[Resource]:
    chain: list[Resource] = []
    current = await get_resource_or_404(db, tenant_id, scope_id)
    while current:
        chain.append(current)
        metadata = current.metadata_json or {}
        if metadata.get("inherit_break") or metadata.get("break_inheritance"):
            break
        if not current.parent_id:
            break
        result = await db.scalars(
            select(Resource).where(
                Resource.id == current.parent_id,
                Resource.tenant_id == tenant_id,
            )
        )
        parent = result.first()
        if not parent:
            break
        current = parent
    return chain


async def _ensure_destination_owner_or_delegator(
    db: AsyncSession, tenant_id: UUID, principal_id: UUID, to_scope_id: UUID
) -> None:
    chain = await _scope_chain(db, tenant_id, to_scope_id)
    scope_ids = [resource.id for resource in chain]
    if not scope_ids:
        raise HTTPException(status_code=404, detail="Destination scope not found")

    result = await db.scalars(
        select(RoleBinding).where(
            RoleBinding.tenant_id == tenant_id,
            RoleBinding.principal_id == principal_id,
            RoleBinding.scope_resource_id.in_(scope_ids),
            RoleBinding.role_name.in_(_OWNER_ROLES),
            RoleBinding.revoked_at.is_(None),
        )
    )
    binding = result.first()
    if not binding:
        raise HTTPException(
            status_code=403,
            detail="Destination approval requires owner or delegator role",
        )


async def _load_subtree(
    db: AsyncSession, tenant_id: UUID, root_id: UUID
) -> list[Resource]:
    root = await get_resource_or_404(db, tenant_id, root_id)
    nodes = [root]
    frontier = [root.id]
    while frontier:
        result = await db.scalars(
            select(Resource)
            .where(
                Resource.tenant_id == tenant_id,
                Resource.parent_id.in_(frontier),
            )
            .order_by(Resource.created_at.asc(), Resource.id.asc())
        )
        children = list(result.all())
        nodes.extend(children)
        frontier = [child.id for child in children]
    return nodes


def _parse_template_bindings(policy: dict) -> list[dict]:
    bindings: list[dict] = []
    raw = policy.get("bindings", [])
    if not isinstance(raw, list):
        return bindings
    for item in raw:
        if not isinstance(item, dict):
            continue
        principal_id = item.get("principal_id")
        role_name = item.get("role_name")
        if not principal_id or not role_name:
            continue
        try:
            principal_uuid = UUID(str(principal_id))
        except ValueError:
            continue
        bindings.append(
            {
                "principal_id": principal_uuid,
                "role_name": str(role_name),
                "apply_to_descendants": bool(item.get("apply_to_descendants", False)),
            }
        )
    return bindings


async def _apply_rbac_template(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    policy: dict,
    root_id: UUID,
    subtree_ids: Iterable[UUID],
    actor_id: UUID,
) -> None:
    bindings = _parse_template_bindings(policy or {})
    if not bindings:
        return
    subtree_list = list(subtree_ids)
    for binding in bindings:
        targets = subtree_list if binding["apply_to_descendants"] else [root_id]
        for scope_id in targets:
            db.add(
                RoleBinding(
                    tenant_id=tenant_id,
                    principal_id=binding["principal_id"],
                    scope_resource_id=scope_id,
                    role_name=binding["role_name"],
                    granted_by=actor_id,
                )
            )
    await db.flush()


@router.post("", response_model=PromotionRequestOut, status_code=201)
async def create_promotion(
    payload: PromotionCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Request promotion",
                "value": {
                    "moving_resource_id": "11111111-1111-1111-1111-111111111111",
                    "to_scope_id": "22222222-2222-2222-2222-222222222222",
                    "placement": {"target": "destination"},
                    "mode": "move",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PromotionRequestOut:
    moving_resource = await get_resource_or_404(
        db, actor.tenant_id, payload.moving_resource_id
    )
    to_scope = await get_resource_or_404(db, actor.tenant_id, payload.to_scope_id)

    if payload.mode not in {"move", "copy"}:
        raise HTTPException(status_code=400, detail="Invalid promotion mode")
    if moving_resource.id == to_scope.id:
        raise HTTPException(status_code=400, detail="Destination scope is invalid")

    await authorize_or_403(
        db, actor, Permission.PROMOTE_REQUEST_CREATE, moving_resource.id
    )
    await authorize_or_403(db, actor, Permission.PROMOTE_REQUEST_CREATE, to_scope.id)

    pr_id = uuid4()
    pr_resource_id = uuid4()
    moving_resource_id = moving_resource.id
    from_scope_id = moving_resource.parent_id
    to_scope_id = to_scope.id
    placement = payload.placement
    mode = payload.mode
    required_approvals = 1

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> PromotionRequest:
        pr_resource = Resource(
            id=pr_resource_id,
            tenant_id=actor.tenant_id,
            type="PromotionRequest",
            parent_id=to_scope_id,
            owner_principal_id=actor.id,
            name=f"Promotion request {pr_id}",
            status="active",
            metadata_json={
                "moving_resource_id": str(moving_resource_id),
                "from_scope_id": str(from_scope_id) if from_scope_id else None,
                "to_scope_id": str(to_scope_id),
                "mode": mode,
                "placement": placement,
            },
        )
        session.add(pr_resource)
        await session.flush()

        pr = PromotionRequest(
            id=pr_id,
            tenant_id=actor.tenant_id,
            pr_resource_id=pr_resource_id,
            moving_resource_id=moving_resource_id,
            from_scope_id=from_scope_id,
            to_scope_id=to_scope_id,
            placement_json=placement,
            rbac_template_ref=payload.rbac_template_ref,
            mode=mode,
            status="open",
            required_approvals=required_approvals,
            created_by=actor.id,
        )
        session.add(pr)
        await session.flush()
        return pr

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=pr_resource_id,
        resource_type="PromotionRequest",
        action="promote.requested",
        payload={
            "pr_id": str(pr_id),
            "moving_resource_id": str(moving_resource_id),
            "from_scope_id": str(from_scope_id) if from_scope_id else None,
            "to_scope_id": str(to_scope_id),
            "mode": mode,
            "placement": placement,
            "rbac_template_ref": payload.rbac_template_ref,
        },
        delivery_channels=[_resource_channel(actor.tenant_id, pr_resource_id)],
    )
    pr, _activity = await tx_activity(db, envelope, domain_fn)
    return PromotionRequestOut.model_validate(pr)


@router.get("/{pr_id}", response_model=PromotionRequestOut)
async def get_promotion(
    pr_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PromotionRequestOut:
    pr = await _get_promotion_request(db, actor.tenant_id, pr_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, pr.pr_resource_id)
    return PromotionRequestOut.model_validate(pr)


@router.post("/{pr_id}/approve", response_model=PromotionApprovalOut)
async def approve_promotion(
    pr_id: UUID,
    payload: PromotionApprovalIn = Body(
        ...,
        examples={
            "default": {
                "summary": "Approve promotion",
                "value": {"decision": "approve", "comment": "Ship it"},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PromotionApprovalOut:
    pr = await _get_promotion_request(db, actor.tenant_id, pr_id)
    to_scope_id = pr.to_scope_id
    pr_resource_id = pr.pr_resource_id
    required_approvals = pr.required_approvals

    await authorize_or_403(db, actor, Permission.PROMOTE_APPROVE, to_scope_id)
    await _ensure_destination_owner_or_delegator(
        db, actor.tenant_id, actor.id, to_scope_id
    )

    if pr.status in {"promoted", "closed"}:
        raise HTTPException(status_code=409, detail="Promotion request is closed")

    decision = payload.decision.lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Invalid decision")

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Approval:
        stmt = (
            pg_insert(Approval)
            .values(
                tenant_id=actor.tenant_id,
                resource_id=pr_resource_id,
                approver_id=actor.id,
                decision=decision,
                comment=payload.comment,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "resource_id", "approver_id"],
                set_={"decision": decision, "comment": payload.comment},
            )
            .returning(Approval)
        )
        result = await session.execute(stmt)
        approval = result.scalar_one()

        pr_row = await _get_promotion_request(session, actor.tenant_id, pr_id)
        approvals, rejects = await _count_approvals(
            session, actor.tenant_id, pr_resource_id
        )
        envelope.payload["counts"] = {
            "approvals": approvals,
            "rejects": rejects,
            "required": required_approvals,
        }
        if rejects > 0:
            pr_row.status = "rejected"
        elif approvals >= required_approvals:
            pr_row.status = "approved"
        else:
            pr_row.status = "open"
        await session.flush()
        return approval

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=pr_resource_id,
        resource_type="PromotionRequest",
        action="promote.approved",
        payload={
            "pr_id": str(pr_id),
            "decision": decision,
            "approver": str(actor.id),
            "counts": {},
        },
        delivery_channels=[_resource_channel(actor.tenant_id, pr_resource_id)],
    )
    _approval, _activity = await tx_activity(db, envelope, domain_fn)

    updated_pr = await _get_promotion_request(db, actor.tenant_id, pr_id)
    approvals_after, rejects_after = await _count_approvals(
        db, actor.tenant_id, pr_resource_id
    )
    return PromotionApprovalOut(
        pr_id=pr_id,
        decision=decision,
        approvals=approvals_after,
        rejects=rejects_after,
        required_approvals=required_approvals,
        status=updated_pr.status,
    )


@router.post("/{pr_id}/execute", response_model=PromotionExecuteOut)
async def execute_promotion(
    pr_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PromotionExecuteOut:
    pr = await _get_promotion_request(db, actor.tenant_id, pr_id)
    if pr.status == "promoted":
        raise HTTPException(status_code=409, detail="Promotion already executed")
    if pr.status != "approved":
        raise HTTPException(status_code=400, detail="Promotion request not approved")

    await authorize_or_403(db, actor, Permission.PROMOTE_EXECUTE, pr.to_scope_id)

    moving_resource_id = pr.moving_resource_id
    to_scope_id = pr.to_scope_id
    mode = pr.mode
    pr_resource_id = pr.pr_resource_id
    rbac_template_ref = pr.rbac_template_ref

    template_policy: Optional[dict] = None
    if rbac_template_ref:
        template_result = await db.scalars(
            select(RbacTemplate).where(
                RbacTemplate.tenant_id == actor.tenant_id,
                RbacTemplate.name == rbac_template_ref,
            )
        )
        template = template_result.first()
        if not template:
            raise HTTPException(status_code=404, detail="RBAC template not found")
        template_policy = dict(template.policy or {})

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Dict[str, Optional[UUID]]:
        pr_row = await _get_promotion_request(session, actor.tenant_id, pr_id)
        subtree = await _load_subtree(session, actor.tenant_id, moving_resource_id)
        subtree_ids = [resource.id for resource in subtree]
        if mode == "move" and to_scope_id in subtree_ids:
            raise HTTPException(
                status_code=400, detail="Destination scope cannot be within subtree"
            )

        moved_count = 0
        copied_count = 0
        new_root_id = moving_resource_id

        if mode == "move":
            root_resource = subtree[0]
            root_resource.parent_id = to_scope_id
            moved_count = len(subtree)
            await session.flush()
            if template_policy is not None:
                await _apply_rbac_template(
                    session,
                    tenant_id=actor.tenant_id,
                    policy=template_policy,
                    root_id=root_resource.id,
                    subtree_ids=subtree_ids,
                    actor_id=actor.id,
                )
        else:
            id_map: Dict[UUID, UUID] = {resource.id: uuid4() for resource in subtree}
            new_resources: List[Resource] = []
            for resource in subtree:
                new_id = id_map[resource.id]
                new_parent_id = (
                    to_scope_id
                    if resource.id == moving_resource_id
                    else id_map[resource.parent_id]
                )
                new_resources.append(
                    Resource(
                        id=new_id,
                        tenant_id=resource.tenant_id,
                        type=resource.type,
                        parent_id=new_parent_id,
                        owner_principal_id=actor.id,
                        space_kind=resource.space_kind,
                        subspace_kind=resource.subspace_kind,
                        name=resource.name,
                        status=resource.status,
                        metadata_json=resource.metadata_json,
                    )
                )
            session.add_all(new_resources)
            await session.flush()

            for resource in new_resources:
                await initialize_versioning(session, resource, actor.id)

            edges = [
                ResourceEdge(
                    tenant_id=actor.tenant_id,
                    src_resource_id=id_map[resource.id],
                    dst_resource_id=resource.id,
                    edge_type="derived_from",
                )
                for resource in subtree
            ]
            session.add_all(edges)
            copied_count = len(new_resources)
            new_root_id = id_map[moving_resource_id]

            if template_policy is not None:
                await _apply_rbac_template(
                    session,
                    tenant_id=actor.tenant_id,
                    policy=template_policy,
                    root_id=new_root_id,
                    subtree_ids=[id_map[res_id] for res_id in subtree_ids],
                    actor_id=actor.id,
                )

        pr_row.status = "promoted"
        await session.flush()

        envelope.payload["counts"] = {
            "moved": moved_count,
            "copied": copied_count,
        }
        envelope.payload["new_root_id"] = str(new_root_id)
        return {
            "new_root_id": new_root_id,
            "moved_count": moved_count,
            "copied_count": copied_count,
        }

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=pr_resource_id,
        resource_type="PromotionRequest",
        action="promote.executed",
        payload={
            "pr_id": str(pr_id),
            "moving_resource_id": str(moving_resource_id),
            "to_scope_id": str(to_scope_id),
            "mode": mode,
            "counts": {"moved": 0, "copied": 0},
            "new_root_id": None,
        },
        delivery_channels=[_resource_channel(actor.tenant_id, pr_resource_id)],
    )
    result, _activity = await tx_activity(db, envelope, domain_fn)
    if result is None:
        raise HTTPException(status_code=409, detail="Promotion already executed")

    return PromotionExecuteOut(
        pr_id=pr_id,
        status="promoted",
        mode=mode,
        new_root_id=result["new_root_id"],
        moved_count=result["moved_count"],
        copied_count=result["copied_count"],
    )
