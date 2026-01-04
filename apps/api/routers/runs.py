"""Runs API Router.

Provides endpoints for Run resources:
- PipelineRun: Dataset refresh with lineage checking
- ExperimentRun: Expression preview with PIT filtering

Phase 2.8d: Run API endpoints for the orchestration layer.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, get_orchestrator, get_status_store
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    ExperimentRunResultsOut,
    ExperimentRunStatusOut,
    ExperimentRunSubmitOut,
    ExperimentRunSubmitRequest,
    PipelineRunStatusOut,
    PipelineRunSubmitOut,
    PipelineRunSubmitRequest,
)
from apps.api.services import ExperimentRunService, PipelineRunService
from libs.core.rbac.models import ActorContext, Permission
from libs.orchestration import OrchestratorAdapter, StatusStore, UpstreamNotReadyError

router = APIRouter(prefix="/runs", tags=["Runs"])


# --- Dependency Functions ---


def get_pipeline_run_service(
    orchestrator: OrchestratorAdapter = Depends(get_orchestrator),
    status_store: StatusStore = Depends(get_status_store),
) -> PipelineRunService:
    """Get PipelineRunService instance."""
    return PipelineRunService(
        orchestrator=orchestrator,
        status_store=status_store,
    )


def get_experiment_run_service(
    orchestrator: OrchestratorAdapter = Depends(get_orchestrator),
    status_store: StatusStore = Depends(get_status_store),
) -> ExperimentRunService:
    """Get ExperimentRunService instance."""
    return ExperimentRunService(
        orchestrator=orchestrator,
        status_store=status_store,
    )


# --- PipelineRun Endpoints ---


@router.post("/pipelines", response_model=PipelineRunSubmitOut, status_code=201)
async def submit_pipeline_run(
    payload: PipelineRunSubmitRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: PipelineRunService = Depends(get_pipeline_run_service),
) -> PipelineRunSubmitOut:
    """Submit a pipeline run for a dataset.

    Triggers a dataset refresh with lineage checking:
    - Checks upstream dependencies are fresh
    - Creates PipelineRun record
    - Triggers Prefect deployment (if available)
    - Updates status on completion

    Args:
        payload: Pipeline run request with dataset_id, mode, and force flag
        actor: Actor context
        db: Database session
        service: PipelineRunService

    Returns:
        Submitted run info with orchestrator details

    Raises:
        400: If upstream dependencies are stale (unless force=True)
        403: If actor lacks permission
        404: If dataset not found
    """
    # Check permission on dataset
    resource = await get_resource_or_404(db, actor.tenant_id, payload.dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    try:
        result = await service.submit_run(
            session=db,
            actor=actor,
            dataset_id=payload.dataset_id,
            mode=payload.mode,
            force=payload.force,
        )
    except UpstreamNotReadyError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "blocking_resources": [str(r) for r in e.blocking_resources],
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PipelineRunSubmitOut(
        id=UUID(result["id"]),
        dataset_id=UUID(result["dataset_id"]),
        orchestrator_run_id=result.get("orchestrator_run_id"),
        orchestrator_kind=result.get("orchestrator_kind"),
        mode=result["mode"],
        status=result["status"],
        started_at=result.get("started_at"),
        upstream_warning=result.get("upstream_warning"),
    )


@router.get("/pipelines/{run_id}", response_model=PipelineRunStatusOut)
async def get_pipeline_run(
    run_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: PipelineRunService = Depends(get_pipeline_run_service),
) -> PipelineRunStatusOut:
    """Get pipeline run status.

    Polls the orchestrator and syncs status if the run is still active.

    Args:
        run_id: PipelineRun resource ID
        actor: Actor context
        db: Database session
        service: PipelineRunService

    Returns:
        Current run status
    """
    resource = await get_resource_or_404(db, actor.tenant_id, run_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    try:
        result = await service.poll_and_sync(session=db, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return PipelineRunStatusOut(
        id=UUID(result["id"]),
        type=result["type"],
        name=result.get("name"),
        dataset_id=UUID(result["dataset_id"]),
        mode=result["mode"],
        status=result["status"],
        orchestrator_kind=result.get("orchestrator_kind"),
        orchestrator_run_id=result.get("orchestrator_run_id"),
        rows_processed=result.get("rows_processed"),
        start_data_date=result.get("start_data_date"),
        end_data_date=result.get("end_data_date"),
        error_summary=result.get("error_summary"),
        started_at=result.get("started_at"),
        finished_at=result.get("finished_at"),
        created_at=result["created_at"],
    )


@router.get("/pipelines", response_model=List[PipelineRunStatusOut])
async def list_pipeline_runs(
    dataset_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(
        default=None, examples=["running", "completed", "failed"]
    ),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: PipelineRunService = Depends(get_pipeline_run_service),
) -> List[PipelineRunStatusOut]:
    """List pipeline runs.

    Args:
        dataset_id: Optional filter by dataset
        status: Optional filter by status
        limit: Maximum results
        actor: Actor context
        db: Database session
        service: PipelineRunService

    Returns:
        List of pipeline run statuses
    """
    results = await service.list_runs(
        session=db,
        actor=actor,
        dataset_id=dataset_id,
        status=status,
        limit=limit,
    )

    return [
        PipelineRunStatusOut(
            id=UUID(r["id"]),
            type=r["type"],
            name=r.get("name"),
            dataset_id=UUID(r["dataset_id"]),
            mode=r["mode"],
            status=r["status"],
            orchestrator_kind=r.get("orchestrator_kind"),
            orchestrator_run_id=r.get("orchestrator_run_id"),
            rows_processed=r.get("rows_processed"),
            start_data_date=r.get("start_data_date"),
            end_data_date=r.get("end_data_date"),
            error_summary=r.get("error_summary"),
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
            created_at=r["created_at"],
        )
        for r in results
    ]


@router.post("/pipelines/{run_id}/cancel", response_model=PipelineRunStatusOut)
async def cancel_pipeline_run(
    run_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: PipelineRunService = Depends(get_pipeline_run_service),
) -> PipelineRunStatusOut:
    """Cancel a running pipeline.

    Args:
        run_id: PipelineRun resource ID
        actor: Actor context
        db: Database session
        service: PipelineRunService

    Returns:
        Updated run status
    """
    resource = await get_resource_or_404(db, actor.tenant_id, run_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    try:
        result = await service.cancel_run(session=db, actor=actor, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PipelineRunStatusOut(
        id=UUID(result["id"]),
        type=result["type"],
        name=result.get("name"),
        dataset_id=UUID(result["dataset_id"]),
        mode=result["mode"],
        status=result["status"],
        orchestrator_kind=result.get("orchestrator_kind"),
        orchestrator_run_id=result.get("orchestrator_run_id"),
        rows_processed=result.get("rows_processed"),
        start_data_date=result.get("start_data_date"),
        end_data_date=result.get("end_data_date"),
        error_summary=result.get("error_summary"),
        started_at=result.get("started_at"),
        finished_at=result.get("finished_at"),
        created_at=result["created_at"],
    )


@router.get("/pipelines/{run_id}/logs")
async def get_pipeline_run_logs(
    run_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: PipelineRunService = Depends(get_pipeline_run_service),
) -> dict:
    """Get execution logs for a pipeline run.

    Args:
        run_id: PipelineRun resource ID
        actor: Actor context
        db: Database session
        service: PipelineRunService

    Returns:
        Logs as text
    """
    resource = await get_resource_or_404(db, actor.tenant_id, run_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    try:
        logs = await service.get_logs(session=db, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"run_id": str(run_id), "logs": logs}


# --- ExperimentRun Endpoints ---


@router.post("/experiments", response_model=ExperimentRunSubmitOut, status_code=201)
async def submit_experiment_run(
    payload: ExperimentRunSubmitRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: ExperimentRunService = Depends(get_experiment_run_service),
) -> ExperimentRunSubmitOut:
    """Submit an experiment preview run.

    Evaluates an expression with optional PIT date filtering:
    - Captures input dataset versions
    - Creates ExperimentRun record
    - Returns preview results (first N rows)

    Args:
        payload: Experiment run request with date filters and limit
        actor: Actor context
        db: Database session
        service: ExperimentRunService

    Returns:
        Submitted run info
    """
    # Check permission on experiment
    resource = await get_resource_or_404(db, actor.tenant_id, payload.experiment_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    # Parse dates
    start_date = None
    end_date = None
    as_of_date = None

    if payload.start_date:
        start_date = date.fromisoformat(payload.start_date)
    if payload.end_date:
        end_date = date.fromisoformat(payload.end_date)
    if payload.as_of_date:
        as_of_date = date.fromisoformat(payload.as_of_date)

    try:
        result = await service.submit_preview(
            session=db,
            actor=actor,
            experiment_id=payload.experiment_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            limit=payload.limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExperimentRunSubmitOut(
        id=UUID(result["id"]),
        experiment_id=UUID(result["experiment_id"]),
        expression=result["expression"],
        orchestrator_run_id=result.get("orchestrator_run_id"),
        orchestrator_kind=result.get("orchestrator_kind"),
        status=result["status"],
        started_at=result.get("started_at"),
    )


@router.get("/experiments/{run_id}", response_model=ExperimentRunStatusOut)
async def get_experiment_run(
    run_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: ExperimentRunService = Depends(get_experiment_run_service),
) -> ExperimentRunStatusOut:
    """Get experiment run status.

    Polls the orchestrator and syncs status if the run is still active.

    Args:
        run_id: ExperimentRun resource ID
        actor: Actor context
        db: Database session
        service: ExperimentRunService

    Returns:
        Current run status
    """
    resource = await get_resource_or_404(db, actor.tenant_id, run_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    try:
        result = await service.poll_and_sync(session=db, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ExperimentRunStatusOut(
        id=UUID(result["id"]),
        type=result["type"],
        name=result.get("name"),
        experiment_id=UUID(result["experiment_id"]),
        expression=result["expression"],
        status=result["status"],
        orchestrator_kind=result.get("orchestrator_kind"),
        orchestrator_run_id=result.get("orchestrator_run_id"),
        start_date=result.get("start_date"),
        end_date=result.get("end_date"),
        as_of_date=result.get("as_of_date"),
        row_count=result.get("row_count"),
        result_columns=result.get("result_columns"),
        started_at=result.get("started_at"),
        finished_at=result.get("finished_at"),
        created_at=result["created_at"],
    )


@router.get("/experiments/{run_id}/results", response_model=ExperimentRunResultsOut)
async def get_experiment_run_results(
    run_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: ExperimentRunService = Depends(get_experiment_run_service),
) -> ExperimentRunResultsOut:
    """Get experiment run results.

    Returns preview data for a completed experiment run.

    Args:
        run_id: ExperimentRun resource ID
        actor: Actor context
        db: Database session
        service: ExperimentRunService

    Returns:
        Preview results including data
    """
    resource = await get_resource_or_404(db, actor.tenant_id, run_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    try:
        result = await service.get_results(session=db, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ExperimentRunResultsOut(
        id=UUID(result["id"]),
        status=result["status"],
        expression=result.get("expression"),
        columns=result.get("columns"),
        row_count=result.get("row_count"),
        preview_data=result.get("preview_data"),
        start_date=result.get("start_date"),
        end_date=result.get("end_date"),
        as_of_date=result.get("as_of_date"),
        message=result.get("message"),
    )


@router.get("/experiments", response_model=List[ExperimentRunStatusOut])
async def list_experiment_runs(
    experiment_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(
        default=None, examples=["running", "completed", "failed"]
    ),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: ExperimentRunService = Depends(get_experiment_run_service),
) -> List[ExperimentRunStatusOut]:
    """List experiment runs.

    Args:
        experiment_id: Optional filter by experiment
        status: Optional filter by status
        limit: Maximum results
        actor: Actor context
        db: Database session
        service: ExperimentRunService

    Returns:
        List of experiment run statuses
    """
    results = await service.list_runs(
        session=db,
        actor=actor,
        experiment_id=experiment_id,
        status=status,
        limit=limit,
    )

    return [
        ExperimentRunStatusOut(
            id=UUID(r["id"]),
            type=r["type"],
            name=r.get("name"),
            experiment_id=UUID(r["experiment_id"]),
            expression=r["expression"],
            status=r["status"],
            orchestrator_kind=r.get("orchestrator_kind"),
            orchestrator_run_id=r.get("orchestrator_run_id"),
            start_date=r.get("start_date"),
            end_date=r.get("end_date"),
            as_of_date=r.get("as_of_date"),
            row_count=r.get("row_count"),
            result_columns=r.get("result_columns"),
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
            created_at=r["created_at"],
        )
        for r in results
    ]


@router.post("/experiments/{run_id}/cancel", response_model=ExperimentRunStatusOut)
async def cancel_experiment_run(
    run_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    service: ExperimentRunService = Depends(get_experiment_run_service),
) -> ExperimentRunStatusOut:
    """Cancel a running experiment.

    Args:
        run_id: ExperimentRun resource ID
        actor: Actor context
        db: Database session
        service: ExperimentRunService

    Returns:
        Updated run status
    """
    resource = await get_resource_or_404(db, actor.tenant_id, run_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    try:
        result = await service.cancel_run(session=db, actor=actor, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExperimentRunStatusOut(
        id=UUID(result["id"]),
        type=result["type"],
        name=result.get("name"),
        experiment_id=UUID(result["experiment_id"]),
        expression=result["expression"],
        status=result["status"],
        orchestrator_kind=result.get("orchestrator_kind"),
        orchestrator_run_id=result.get("orchestrator_run_id"),
        start_date=result.get("start_date"),
        end_date=result.get("end_date"),
        as_of_date=result.get("as_of_date"),
        row_count=result.get("row_count"),
        result_columns=result.get("result_columns"),
        started_at=result.get("started_at"),
        finished_at=result.get("finished_at"),
        created_at=result["created_at"],
    )
