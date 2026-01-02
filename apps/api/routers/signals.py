"""Signals API Router.

Provides endpoints for:
- Registering datasets as signals
- Getting signal specifications
- Validating signals against specs
- Promoting signals to official
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    SignalOut,
    SignalRegisterRequest,
    SignalValidateOut,
)
from apps.api.services import SignalService
from libs.core.rbac.models import ActorContext, Permission

router = APIRouter(prefix="/signals", tags=["Signals"])


@router.post("", response_model=SignalOut, status_code=201)
async def register_signal(
    payload: SignalRegisterRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SignalOut:
    """Register a dataset as a signal.

    Creates a SignalSpec resource with validation bounds.

    Args:
        payload: Signal registration details
        actor: Actor context
        db: Database session

    Returns:
        Created signal info
    """
    # Check permission on parent resource
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    # Check permission on source dataset
    dataset = await get_resource_or_404(db, actor.tenant_id, payload.dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, dataset.id)

    service = SignalService()
    try:
        result = await service.register_signal(
            session=db,
            actor=actor,
            dataset_id=payload.dataset_id,
            name=payload.name,
            parent_id=payload.parent_id,
            min_value=payload.min_value,
            max_value=payload.max_value,
            allow_nan=payload.allow_nan,
            neutral_value=payload.neutral_value,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SignalOut(
        id=UUID(result["id"]),
        name=result["name"],
        min_value=result["min_value"],
        max_value=result["max_value"],
        allow_nan=result["allow_nan"],
        neutral_value=result["neutral_value"],
        status=result["status"],
    )


@router.get("/{signal_id}", response_model=SignalOut)
async def get_signal(
    signal_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SignalOut:
    """Get signal specification.

    Args:
        signal_id: Signal resource ID
        actor: Actor context
        db: Database session

    Returns:
        Signal spec info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, signal_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = SignalService()
    result = await service.get_signal(
        session=db,
        tenant_id=actor.tenant_id,
        signal_id=signal_id,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Signal not found")

    return SignalOut(
        id=UUID(result["id"]),
        name=result["name"],
        min_value=result["min_value"],
        max_value=result["max_value"],
        allow_nan=result["allow_nan"],
        neutral_value=result["neutral_value"],
        status=result["status"],
    )


@router.post("/{signal_id}/validate", response_model=SignalValidateOut)
async def validate_signal(
    signal_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SignalValidateOut:
    """Validate signal data against its specification.

    Checks that all values fall within bounds and conform to spec.

    Args:
        signal_id: Signal resource ID
        actor: Actor context
        db: Database session

    Returns:
        Validation result
    """
    resource = await get_resource_or_404(db, actor.tenant_id, signal_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = SignalService()
    try:
        result = await service.validate_signal(
            session=db,
            actor=actor,
            signal_id=signal_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SignalValidateOut(
        id=signal_id,
        valid=result["valid"],
        issues=result.get("issues", []),
    )


@router.post("/{signal_id}/promote", response_model=SignalOut)
async def promote_signal(
    signal_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SignalOut:
    """Promote signal to official status.

    Requires passing validation and appropriate permissions.

    Args:
        signal_id: Signal resource ID
        actor: Actor context
        db: Database session

    Returns:
        Promoted signal info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, signal_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = SignalService()
    try:
        result = await service.promote_signal(
            session=db,
            actor=actor,
            signal_id=signal_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SignalOut(
        id=UUID(result["id"]),
        name=result["name"],
        min_value=result["min_value"],
        max_value=result["max_value"],
        allow_nan=result["allow_nan"],
        neutral_value=result["neutral_value"],
        status=result["status"],
    )


@router.get("", response_model=List[SignalOut])
async def list_signals(
    parent_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(default=None, examples=["staging", "official"]),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[SignalOut]:
    """List signals.

    Args:
        parent_id: Optional parent resource filter
        status: Optional status filter
        limit: Maximum results
        actor: Actor context
        db: Database session

    Returns:
        List of signal info
    """
    service = SignalService()
    results = await service.list_signals(
        session=db,
        actor=actor,
        parent_id=parent_id,
        status=status,
        limit=limit,
    )

    return [
        SignalOut(
            id=UUID(r["id"]),
            name=r["name"],
            min_value=r["min_value"],
            max_value=r["max_value"],
            allow_nan=r["allow_nan"],
            neutral_value=r["neutral_value"],
            status=r["status"],
        )
        for r in results
    ]
