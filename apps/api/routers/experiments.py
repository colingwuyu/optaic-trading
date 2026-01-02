"""Experiments API Router.

Provides endpoints for:
- Creating expression experiments
- Running experiments (previewing expressions)
- Saving experiments as macros
- Managing experiment lifecycle
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    ExperimentCreate,
    ExperimentOut,
    ExperimentRunOut,
    ExperimentRunRequest,
    ExperimentUpdate,
    MacroSaveOut,
)
from apps.api.services import ExperimentService
from libs.core.rbac.models import ActorContext, Permission

router = APIRouter(prefix="/experiments", tags=["Experiments"])


@router.post("", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    payload: ExperimentCreate = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ExperimentOut:
    """Create a new expression experiment.

    Experiments allow writing and testing expressions before
    saving them as reusable macros.

    Args:
        payload: Experiment details including expression
        actor: Actor context
        db: Database session

    Returns:
        Created experiment info
    """
    # Check permission on parent resource
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    service = ExperimentService()
    try:
        result = await service.create_experiment(
            session=db,
            actor=actor,
            name=payload.name,
            expression=payload.expression,
            parent_id=payload.parent_id,
            input_datasets=payload.input_datasets,
            description=payload.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExperimentOut(
        id=UUID(result["id"]),
        name=result["name"],
        expression=result["expression"],
        operators_used=result.get("operators_used", []),
        datasets_referenced=result.get("datasets_referenced", []),
        status=result["status"],
    )


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    experiment_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ExperimentOut:
    """Get experiment details.

    Args:
        experiment_id: Experiment resource ID
        actor: Actor context
        db: Database session

    Returns:
        Experiment info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, experiment_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = ExperimentService()
    result = await service.get_experiment(
        session=db,
        tenant_id=actor.tenant_id,
        experiment_id=experiment_id,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Experiment not found")

    return ExperimentOut(
        id=UUID(result["id"]),
        name=result["name"],
        expression=result["expression"],
        operators_used=result.get("operators_used", []),
        datasets_referenced=result.get("datasets_referenced", []),
        status="active",
    )


@router.post("/{experiment_id}/run", response_model=ExperimentRunOut)
async def run_experiment(
    experiment_id: UUID,
    payload: ExperimentRunRequest = Body(ExperimentRunRequest()),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ExperimentRunOut:
    """Run an experiment and return preview results.

    Args:
        experiment_id: Experiment resource ID
        payload: Run parameters
        actor: Actor context
        db: Database session

    Returns:
        Experiment run results
    """
    resource = await get_resource_or_404(db, actor.tenant_id, experiment_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = ExperimentService()

    # TODO: Load actual DataFrames from input_datasets
    # For now, run with empty context (expression validation only)
    try:
        result = await service.run_experiment(
            session=db,
            actor=actor,
            experiment_id=experiment_id,
            context={},  # Would load DataFrames from experiment's input_datasets
            limit=payload.limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExperimentRunOut(
        id=experiment_id if result.get("success") else None,
        success=result.get("success", False),
        name=result.get("name"),
        expression=result.get("expression"),
        result_type=result.get("result_type"),
        columns=result.get("columns"),
        data=result.get("data"),
        value=result.get("value"),
        row_count=result.get("row_count"),
        truncated=result.get("truncated"),
        error=result.get("error"),
    )


@router.patch("/{experiment_id}", response_model=ExperimentOut)
async def update_experiment(
    experiment_id: UUID,
    payload: ExperimentUpdate = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ExperimentOut:
    """Update an experiment.

    Args:
        experiment_id: Experiment resource ID
        payload: Update details
        actor: Actor context
        db: Database session

    Returns:
        Updated experiment info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, experiment_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = ExperimentService()
    try:
        result = await service.update_experiment(
            session=db,
            actor=actor,
            experiment_id=experiment_id,
            expression=payload.expression,
            input_datasets=payload.input_datasets,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExperimentOut(
        id=UUID(result["id"]),
        name=result["name"],
        expression=result["expression"],
        operators_used=[],  # Would be extracted from expression
        datasets_referenced=[],
        status=result["status"],
    )


@router.post("/{experiment_id}/save-as-macro", response_model=MacroSaveOut)
async def save_as_macro(
    experiment_id: UUID,
    macro_name: Optional[str] = Query(default=None, examples=["my_momentum_macro"]),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MacroSaveOut:
    """Save an experiment as a reusable macro.

    Creates an OpMacroDef resource from the experiment.

    Args:
        experiment_id: Experiment resource ID
        macro_name: Optional override for macro name
        actor: Actor context
        db: Database session

    Returns:
        Macro info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, experiment_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = ExperimentService()
    try:
        result = await service.save_as_macro(
            session=db,
            actor=actor,
            experiment_id=experiment_id,
            macro_name=macro_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MacroSaveOut(
        id=UUID(result["id"]),
        name=result["name"],
        expression=result["expression"],
        input_aliases=result["input_aliases"],
        status=result["status"],
    )


@router.get("", response_model=List[ExperimentOut])
async def list_experiments(
    parent_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[ExperimentOut]:
    """List experiments.

    Args:
        parent_id: Optional parent resource filter
        limit: Maximum results
        actor: Actor context
        db: Database session

    Returns:
        List of experiment info
    """
    service = ExperimentService()
    results = await service.list_experiments(
        session=db,
        actor=actor,
        parent_id=parent_id,
        limit=limit,
    )

    return [
        ExperimentOut(
            id=UUID(r["id"]),
            name=r["name"],
            expression=r["expression"],
            operators_used=[],
            datasets_referenced=[],
            status="active",
        )
        for r in results
    ]
