"""Governance API endpoints.

Provides endpoints for resource governance operations:
- Copy (reference): Same artifact_ref, no RBAC change
- Branch: New artifact_ref (copied files), actor=owner, source_owner=viewer
- Transfer: Request/accept workflow, recipient chooses project
- Promote: To staging, approval-based auto-move to official
- Merge: Branch artifact replaces ancestor, contributor credit

Resource Type Rules:
- Flow resources (runs): View-only, no governance actions
- Scope resources (Projects): Copy, transfer, promote (no branch/merge)
- Definition/Instance: All governance actions allowed
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from libs.core.governance import (
    GovernanceService,
    PlacementError,
    ResourceTypeError,
)
from libs.core.rbac.models import ActorContext, Permission

router = APIRouter(prefix="/governance", tags=["Governance"])


# ============================================================================
# Schemas
# ============================================================================


class GovernanceCopyIn(BaseModel):
    """Request to copy a resource by reference."""

    target_parent_id: UUID = Field(
        description="Target parent resource ID",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    name: Optional[str] = Field(
        default=None,
        description="Optional new name for the copy",
        examples=["My Copy"],
    )


class GovernanceBranchIn(BaseModel):
    """Request to branch a resource (with file copy)."""

    target_parent_id: UUID = Field(
        description="Target parent resource ID",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    name: Optional[str] = Field(
        default=None,
        description="Optional name for the branch",
        examples=["Feature Branch"],
    )


class GovernanceTransferIn(BaseModel):
    """Request to transfer resource ownership (legacy direct transfer)."""

    target_owner_id: UUID = Field(
        description="New owner principal ID",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )


class TransferRequestIn(BaseModel):
    """Request to initiate a transfer request workflow."""

    recipient_id: UUID = Field(
        description="Proposed new owner principal ID",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    message: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Optional message to recipient",
        examples=["I'd like to transfer this to you for the Q4 project"],
    )


class TransferAcceptIn(BaseModel):
    """Request to accept a transfer and specify destination."""

    destination_project_id: UUID = Field(
        description="Project to place the transferred resource",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    response_message: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Optional response message",
        examples=["Thanks! Moving to my production project"],
    )


class TransferRejectIn(BaseModel):
    """Request to reject a transfer."""

    response_message: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Optional rejection reason",
        examples=["Sorry, I don't have capacity for this right now"],
    )


class TransferRequestOut(BaseModel):
    """Response for transfer request operations."""

    id: UUID
    resource_id: UUID
    sender_id: Optional[UUID] = None
    recipient_id: Optional[UUID] = None
    destination_project_id: Optional[UUID] = None
    status: str
    expires_at: Optional[str] = None
    operation: str


class PromotionApproveIn(BaseModel):
    """Request to approve a promotion."""

    comment: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Optional approval comment",
        examples=["Reviewed and approved for production"],
    )


class PromotionApprovalOut(BaseModel):
    """Response for promotion approval."""

    promotion_request_id: UUID
    approver_id: UUID
    approval_count: int
    required_approvals: int
    status: str
    resource_id: Optional[UUID] = None
    moved_to: Optional[str] = None
    operation: str


class GovernancePromoteIn(BaseModel):
    """Request to promote a resource to a team space."""

    target_space_id: UUID = Field(
        description="Target team space ID",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    team_principal_id: UUID = Field(
        description="Team principal ID (new owner)",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    name: Optional[str] = Field(
        default=None,
        description="Optional new name for promoted resource",
        examples=["Official Pipeline"],
    )


class GovernanceMergeIn(BaseModel):
    """Request to merge a branch back to its ancestor."""

    target_id: UUID = Field(
        description="Target resource ID (ancestor to update)",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )


class GovernanceOperationOut(BaseModel):
    """Response for governance operations."""

    id: UUID
    name: str
    type: str
    operation: str
    source_id: Optional[UUID] = None
    target_id: Optional[UUID] = None
    artifact_ref: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    previous_owner_id: Optional[UUID] = None
    team_principal_id: Optional[UUID] = None
    contributor_id: Optional[UUID] = None
    subspace_kind: Optional[str] = None
    promotion_request_id: Optional[UUID] = None
    status: Optional[str] = None


class LineageEntry(BaseModel):
    """A single lineage entry."""

    id: UUID
    name: str
    type: str
    depth: int
    edge_type: Optional[str] = None


class LineageOut(BaseModel):
    """Response for lineage queries."""

    resource_id: UUID
    direction: str
    entries: list[LineageEntry]


# ============================================================================
# Dependencies
# ============================================================================


def get_governance_service() -> GovernanceService:
    """Get the governance service instance."""
    return GovernanceService()


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/resources/{resource_id}/copy",
    response_model=GovernanceOperationOut,
    status_code=201,
)
async def copy_resource(
    resource_id: UUID,
    payload: GovernanceCopyIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> GovernanceOperationOut:
    """Copy a resource by reference (no file copy).

    Creates a new resource that references the same artifact.
    RBAC bindings are NOT changed - user keeps their existing role.

    Requires:
    - RESOURCE_READ on the source resource
    - RESOURCE_CREATE_CHILD on the target parent
    """
    # Verify permissions
    await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource_id)

    await get_resource_or_404(db, actor.tenant_id, payload.target_parent_id)
    await authorize_or_403(
        db, actor, Permission.RESOURCE_CREATE_CHILD, payload.target_parent_id
    )

    try:
        result = await service.copy_resource(
            db,
            actor,
            source_id=resource_id,
            target_parent_id=payload.target_parent_id,
            name=payload.name,
        )
    except ResourceTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PlacementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return GovernanceOperationOut(
        id=UUID(result["id"]),
        name=result["name"],
        type=result["type"],
        operation=result["operation"],
        source_id=UUID(result["source_id"]),
        artifact_ref=UUID(result["artifact_ref"])
        if result.get("artifact_ref")
        else None,
    )


@router.post(
    "/resources/{resource_id}/branch",
    response_model=GovernanceOperationOut,
    status_code=201,
)
async def branch_resource(
    resource_id: UUID,
    payload: GovernanceBranchIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> GovernanceOperationOut:
    """Branch a resource (with file copy).

    Creates a new resource with COPIED artifact files.
    RBAC mutations:
    - Actor becomes owner of new resource
    - Source owner gets viewer role on new resource

    Requires:
    - RESOURCE_READ on the source resource
    - RESOURCE_CREATE_CHILD on the target parent
    """
    # Verify permissions
    await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource_id)

    await get_resource_or_404(db, actor.tenant_id, payload.target_parent_id)
    await authorize_or_403(
        db, actor, Permission.RESOURCE_CREATE_CHILD, payload.target_parent_id
    )

    try:
        result = await service.branch_resource(
            db,
            actor,
            source_id=resource_id,
            target_parent_id=payload.target_parent_id,
            name=payload.name,
        )
    except ResourceTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PlacementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return GovernanceOperationOut(
        id=UUID(result["id"]),
        name=result["name"],
        type=result["type"],
        operation=result["operation"],
        source_id=UUID(result["source_id"]),
        artifact_ref=UUID(result["artifact_ref"])
        if result.get("artifact_ref")
        else None,
    )


@router.post(
    "/resources/{resource_id}/transfer",
    response_model=GovernanceOperationOut,
    status_code=200,
)
async def transfer_resource(
    resource_id: UUID,
    payload: GovernanceTransferIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> GovernanceOperationOut:
    """Transfer ownership of a resource.

    Changes ownership without copying files.
    RBAC mutations:
    - Target becomes owner
    - Previous owner becomes viewer

    Requires:
    - Actor must be current owner of the resource
    """
    # Verify resource exists
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)

    # Verify actor is owner
    if resource.owner_principal_id != actor.id:
        raise HTTPException(
            status_code=403, detail="Only the owner can transfer a resource"
        )

    result = await service.transfer_resource(
        db,
        actor,
        resource_id=resource_id,
        target_owner_id=payload.target_owner_id,
    )

    await db.commit()

    return GovernanceOperationOut(
        id=UUID(result["id"]),
        name=result["name"],
        type=result["type"],
        operation=result["operation"],
        owner_id=UUID(result["owner_id"]),
        previous_owner_id=UUID(result["previous_owner_id"]),
    )


@router.post(
    "/resources/{resource_id}/promote",
    response_model=GovernanceOperationOut,
    status_code=201,
)
async def promote_resource(
    resource_id: UUID,
    payload: GovernancePromoteIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> GovernanceOperationOut:
    """Promote a resource to a team space.

    Copies artifacts to team space with RBAC mutations:
    - Team becomes owner
    - Promoter gets delegator role

    Requires:
    - RESOURCE_READ on the source resource
    - RESOURCE_CREATE_CHILD on the target space
    - Appropriate team membership/permissions
    """
    # Verify permissions
    await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource_id)

    await get_resource_or_404(db, actor.tenant_id, payload.target_space_id)
    await authorize_or_403(
        db, actor, Permission.RESOURCE_CREATE_CHILD, payload.target_space_id
    )

    try:
        result = await service.promote_resource(
            db,
            actor,
            source_id=resource_id,
            target_space_id=payload.target_space_id,
            team_principal_id=payload.team_principal_id,
            name=payload.name,
        )
    except ResourceTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PlacementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return GovernanceOperationOut(
        id=UUID(result["id"]),
        name=result["name"],
        type=result["type"],
        operation=result["operation"],
        source_id=UUID(result["source_id"]),
        team_principal_id=UUID(result["team_principal_id"]),
        artifact_ref=UUID(result["artifact_ref"])
        if result.get("artifact_ref")
        else None,
        subspace_kind=result.get("subspace_kind"),
        promotion_request_id=UUID(result["promotion_request_id"])
        if result.get("promotion_request_id")
        else None,
        status=result.get("status"),
    )


@router.post(
    "/resources/{resource_id}/merge",
    response_model=GovernanceOperationOut,
    status_code=200,
)
async def merge_resource(
    resource_id: UUID,
    payload: GovernanceMergeIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> GovernanceOperationOut:
    """Merge a branch back to its ancestor.

    Replaces the ancestor's artifact with the branch's artifact.
    The source (branch) is marked as merged.
    Contributor credit is tracked via lineage edge.

    Requires:
    - RESOURCE_UPDATE on the target (ancestor) resource
    - Source must be a branch of target
    """
    # Verify source (branch) exists
    await get_resource_or_404(db, actor.tenant_id, resource_id)

    # Verify target exists and actor can update it
    await get_resource_or_404(db, actor.tenant_id, payload.target_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, payload.target_id)

    try:
        result = await service.merge_resource(
            db,
            actor,
            source_id=resource_id,
            target_id=payload.target_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return GovernanceOperationOut(
        id=UUID(result["target_id"]),
        name="",  # Could fetch resource name if needed
        type="",  # Could fetch resource type if needed
        operation=result["operation"],
        source_id=UUID(result["source_id"]),
        target_id=UUID(result["target_id"]),
        contributor_id=UUID(result["contributor_id"]),
        artifact_ref=UUID(result["artifact_ref"])
        if result.get("artifact_ref")
        else None,
    )


@router.get(
    "/resources/{resource_id}/lineage",
    response_model=LineageOut,
)
async def get_resource_lineage(
    resource_id: UUID,
    direction: str = Query(
        default="upstream",
        description="Lineage direction: upstream or downstream",
    ),
    edge_types: Optional[str] = Query(
        default=None,
        description="Comma-separated edge types to filter (e.g., branch_of,promoted_from)",
    ),
    max_depth: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Maximum traversal depth",
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> LineageOut:
    """Get resource lineage (ancestors or descendants).

    Returns the lineage chain for a resource, showing:
    - For upstream: what resources this was derived from
    - For downstream: what resources were derived from this

    Edge types include: copy_of, branch_of, promoted_from, merged_from
    """
    # Verify resource exists
    await get_resource_or_404(db, actor.tenant_id, resource_id)

    # Parse edge types if provided
    filter_edge_types = None
    if edge_types:
        filter_edge_types = [t.strip() for t in edge_types.split(",")]

    lineage = await service.get_resource_lineage(
        db,
        actor,
        resource_id,
        direction=direction,
        edge_types=filter_edge_types,
        max_depth=max_depth,
    )

    return LineageOut(
        resource_id=resource_id,
        direction=direction,
        entries=[
            LineageEntry(
                id=UUID(entry["id"]),
                name=entry["name"],
                type=entry["type"],
                depth=entry["depth"],
                edge_type=entry.get("edge_type"),
            )
            for entry in lineage
        ],
    )


# ============================================================================
# Transfer Request Workflow Endpoints
# ============================================================================


@router.post(
    "/resources/{resource_id}/transfer-request",
    response_model=TransferRequestOut,
    status_code=201,
)
async def create_transfer_request(
    resource_id: UUID,
    payload: TransferRequestIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> TransferRequestOut:
    """Create a transfer request for a resource.

    Initiates the transfer workflow:
    1. Sender creates request
    2. Recipient receives notification
    3. Recipient accepts/rejects with destination project

    Requires:
    - Actor must be current owner of the resource
    """
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)

    if resource.owner_principal_id != actor.id:
        raise HTTPException(
            status_code=403, detail="Only the owner can initiate a transfer request"
        )

    try:
        result = await service.create_transfer_request(
            db,
            actor,
            resource_id=resource_id,
            recipient_id=payload.recipient_id,
            message=payload.message,
        )
    except ResourceTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return TransferRequestOut(
        id=UUID(result["id"]),
        resource_id=UUID(result["resource_id"]),
        sender_id=UUID(result["sender_id"]),
        recipient_id=UUID(result["recipient_id"]),
        status=result["status"],
        expires_at=result.get("expires_at"),
        operation=result["operation"],
    )


@router.post(
    "/transfers/{transfer_request_id}/accept",
    response_model=GovernanceOperationOut,
    status_code=200,
)
async def accept_transfer_request(
    transfer_request_id: UUID,
    payload: TransferAcceptIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> GovernanceOperationOut:
    """Accept a transfer request and move resource to destination project.

    Completes the transfer:
    1. Validates recipient and destination
    2. Moves resource to destination project
    3. Updates ownership and RBAC
    4. Marks request as accepted

    Requires:
    - Actor must be the recipient of the transfer request
    """
    try:
        result = await service.accept_transfer(
            db,
            actor,
            transfer_request_id=transfer_request_id,
            destination_project_id=payload.destination_project_id,
            response_message=payload.response_message,
        )
    except PlacementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return GovernanceOperationOut(
        id=UUID(result["id"]),
        name=result["name"],
        type=result["type"],
        operation=result["operation"],
        owner_id=UUID(result["owner_id"]),
        previous_owner_id=UUID(result["previous_owner_id"]),
    )


@router.post(
    "/transfers/{transfer_request_id}/reject",
    response_model=TransferRequestOut,
    status_code=200,
)
async def reject_transfer_request(
    transfer_request_id: UUID,
    payload: TransferRejectIn = Body(default=TransferRejectIn()),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> TransferRequestOut:
    """Reject a transfer request.

    Requires:
    - Actor must be the recipient of the transfer request
    """
    try:
        result = await service.reject_transfer(
            db,
            actor,
            transfer_request_id=transfer_request_id,
            response_message=payload.response_message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return TransferRequestOut(
        id=UUID(result["id"]),
        resource_id=UUID(result["resource_id"]),
        status=result["status"],
        operation=result["operation"],
    )


@router.post(
    "/transfers/{transfer_request_id}/cancel",
    response_model=TransferRequestOut,
    status_code=200,
)
async def cancel_transfer_request(
    transfer_request_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> TransferRequestOut:
    """Cancel a transfer request (by sender).

    Requires:
    - Actor must be the sender of the transfer request
    """
    try:
        result = await service.cancel_transfer(
            db,
            actor,
            transfer_request_id=transfer_request_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return TransferRequestOut(
        id=UUID(result["id"]),
        resource_id=UUID(result["resource_id"]),
        status=result["status"],
        operation=result["operation"],
    )


# ============================================================================
# Promotion Approval Endpoints
# ============================================================================


@router.post(
    "/promotions/{promotion_request_id}/approve",
    response_model=PromotionApprovalOut,
    status_code=200,
)
async def approve_promotion(
    promotion_request_id: UUID,
    payload: PromotionApproveIn = Body(default=PromotionApproveIn()),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service),
) -> PromotionApprovalOut:
    """Approve a promotion request.

    When all required approvals are met, the resource is:
    1. Moved from staging to official subspace
    2. Status updated to 'active'

    Requires:
    - Actor must have approval permission on the promotion request
    """
    try:
        result = await service.approve_promotion(
            db,
            actor,
            promotion_request_id=promotion_request_id,
            comment=payload.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await db.commit()

    return PromotionApprovalOut(
        promotion_request_id=UUID(result["promotion_request_id"]),
        approver_id=UUID(result["approver_id"]),
        approval_count=result["approval_count"],
        required_approvals=result["required_approvals"],
        status=result.get("status", "pending"),
        resource_id=UUID(result["resource_id"]) if result.get("resource_id") else None,
        moved_to=result.get("moved_to"),
        operation=result["operation"],
    )
