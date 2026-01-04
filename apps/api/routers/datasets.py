"""Datasets API Router.

Provides endpoints for:
- Creating dataset instances
- Previewing dataset data (PIT-aware)
- Checking dataset status
- Triggering dataset refresh
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    DatasetCreate,
    DatasetOut,
    DatasetPreviewOut,
    DatasetPreviewRequest,
    DatasetRefreshOut,
    DatasetScheduleOut,
    DatasetStatusOut,
    LineageDAGOut,
    LineageEdgeOut,
    LineageFreshnessOut,
    LineageNodeOut,
    ScheduleConfigIn,
    ScheduleConfigOut,
)
from apps.api.services import DatasetService
from libs.core.rbac.models import ActorContext, Permission

router = APIRouter(prefix="/datasets", tags=["Datasets"])


@router.post("", response_model=DatasetOut, status_code=201)
async def create_dataset(
    payload: DatasetCreate = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    """Create a new dataset instance.

    A DatasetInstance combines:
    - A PipelineInstance (data source/transformation)
    - A StoreInstance (where data is stored)
    - An AccessorInstance (how data is retrieved)

    Args:
        payload: Dataset creation details
        actor: Actor context
        db: Database session

    Returns:
        Created dataset info
    """
    # Check permission on parent resource
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    service = DatasetService()
    try:
        result = await service.create_dataset(
            session=db,
            actor=actor,
            name=payload.name,
            parent_id=payload.parent_id,
            pipeline_instance_id=payload.pipeline_instance_id,
            store_instance_id=payload.store_instance_id,
            accessor_instance_id=payload.accessor_instance_id,
            freshness_status=payload.freshness_status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DatasetOut(
        id=UUID(result["id"]),
        name=result["name"],
        type=result["type"],
        status=result["status"],
        freshness_status=result["freshness_status"],
        pipeline_instance_id=UUID(result["pipeline_instance_id"]),
        store_instance_id=UUID(result["store_instance_id"]),
        accessor_instance_id=UUID(result["accessor_instance_id"]),
    )


@router.get("/{dataset_id}", response_model=DatasetStatusOut)
async def get_dataset(
    dataset_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetStatusOut:
    """Get dataset info.

    Args:
        dataset_id: Dataset resource ID
        actor: Actor context
        db: Database session

    Returns:
        Dataset info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = DatasetService()
    status = await service.get_status(
        session=db,
        tenant_id=actor.tenant_id,
        dataset_id=dataset_id,
    )

    if not status:
        raise HTTPException(status_code=404, detail="Dataset not found")

    return DatasetStatusOut(
        id=UUID(status["id"]),
        name=status["name"],
        freshness_status=status["freshness_status"],
        last_data_date=status.get("last_data_date"),
        row_count=status.get("row_count"),
    )


@router.get("", response_model=list[DatasetStatusOut])
async def list_datasets(
    parent_id: Optional[UUID] = Query(default=None),
    freshness_status: Optional[str] = Query(default=None, examples=["fresh", "stale"]),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> list[DatasetStatusOut]:
    """List datasets.

    Args:
        parent_id: Optional parent resource filter
        freshness_status: Optional freshness filter
        limit: Maximum results
        actor: Actor context
        db: Database session

    Returns:
        List of dataset info
    """
    service = DatasetService()
    results = await service.list_datasets(
        session=db,
        actor=actor,
        parent_id=parent_id,
        freshness_status=freshness_status,
        limit=limit,
    )

    return [
        DatasetStatusOut(
            id=UUID(r["id"]),
            name=r["name"],
            freshness_status=r["freshness_status"],
            last_data_date=r["last_data_date"],
            row_count=r["row_count"],
        )
        for r in results
    ]


@router.get("/{dataset_id}/status", response_model=DatasetStatusOut)
async def get_dataset_status(
    dataset_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetStatusOut:
    """Get dataset freshness status.

    Args:
        dataset_id: Dataset resource ID
        actor: Actor context
        db: Database session

    Returns:
        Dataset status info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = DatasetService()
    status = await service.get_status(
        session=db,
        tenant_id=actor.tenant_id,
        dataset_id=dataset_id,
    )

    if not status:
        raise HTTPException(status_code=404, detail="Dataset not found")

    return DatasetStatusOut(
        id=UUID(status["id"]),
        name=status["name"],
        freshness_status=status["freshness_status"],
        last_data_date=status.get("last_data_date"),
        row_count=status.get("row_count"),
    )


@router.post("/{dataset_id}/preview", response_model=DatasetPreviewOut)
async def preview_dataset(
    dataset_id: UUID,
    payload: DatasetPreviewRequest = Body(DatasetPreviewRequest()),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetPreviewOut:
    """Preview dataset data.

    Supports PIT (point-in-time) queries via as_of_date parameter.

    Args:
        dataset_id: Dataset resource ID
        payload: Preview parameters
        actor: Actor context
        db: Database session

    Returns:
        Dataset preview with data sample
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = DatasetService()
    try:
        result = await service.preview(
            session=db,
            actor=actor,
            dataset_id=dataset_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            as_of_date=payload.as_of_date,
            limit=payload.limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DatasetPreviewOut(
        id=UUID(result["id"]),
        name=result["name"],
        columns=result["columns"],
        data=result["data"],
        row_count=result["row_count"],
        truncated=result["truncated"],
    )


@router.post("/{dataset_id}/refresh", response_model=DatasetRefreshOut)
async def refresh_dataset(
    dataset_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetRefreshOut:
    """Trigger dataset refresh.

    Queues the dataset for refresh by running its associated pipeline.

    Args:
        dataset_id: Dataset resource ID
        actor: Actor context
        db: Database session

    Returns:
        Refresh status
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = DatasetService()
    try:
        result = await service.refresh(
            session=db,
            actor=actor,
            dataset_id=dataset_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DatasetRefreshOut(
        id=UUID(result["id"]),
        name=result["name"],
        status=result["status"],
        message=result["message"],
    )


@router.get("/{dataset_id}/lineage", response_model=LineageDAGOut)
async def get_dataset_lineage(
    dataset_id: UUID,
    direction: str = Query(
        default="both",
        pattern="^(upstream|downstream|both)$",
        description="Direction to traverse: upstream, downstream, or both",
    ),
    depth: int = Query(
        default=3,
        ge=1,
        le=10,
        description="Maximum traversal depth",
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> LineageDAGOut:
    """Get lineage DAG for visualization.

    Returns a graph structure suitable for visualization libraries
    like D3.js, Dagre, or Cytoscape.

    The response includes:
    - nodes: All resources in the lineage graph
    - edges: Dependencies between resources
    - execution_order: Topologically sorted batches for parallel execution
    - freshness: Current freshness status of upstreams

    Args:
        dataset_id: Dataset resource ID
        direction: Traversal direction (upstream, downstream, both)
        depth: Maximum traversal depth (1-10)
        actor: Actor context
        db: Database session

    Returns:
        LineageDAGOut with graph data for visualization
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = DatasetService()
    result = await service.get_lineage_dag(
        session=db,
        actor=actor,
        dataset_id=dataset_id,
        direction=direction,
        depth=depth,
    )

    # Convert to response model
    nodes = [
        LineageNodeOut(
            id=n["id"],
            name=n["name"],
            type=n["type"],
            status=n.get("status"),
            direction=n["direction"],
        )
        for n in result["nodes"]
    ]

    edges = [
        LineageEdgeOut(
            source=e["source"],
            target=e["target"],
            kind=e.get("kind", "data_dependency"),
        )
        for e in result["edges"]
    ]

    freshness = None
    if result.get("freshness"):
        freshness = LineageFreshnessOut(
            all_ready=result["freshness"]["all_ready"],
            blockers=result["freshness"]["blockers"],
        )

    return LineageDAGOut(
        nodes=nodes,
        edges=edges,
        center_id=result["center_id"],
        execution_order=result["execution_order"],
        freshness=freshness,
    )


# --- Schedule Management Endpoints (Phase 2.8.5) ---


@router.get("/{dataset_id}/schedule", response_model=DatasetScheduleOut)
async def get_dataset_schedule(
    dataset_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetScheduleOut:
    """Get schedule configuration for a dataset.

    Returns the current schedule settings including:
    - cron expression or interval
    - active status
    - deployment ID and orchestrator info

    Args:
        dataset_id: Dataset resource ID
        actor: Actor context
        db: Database session

    Returns:
        DatasetScheduleOut with schedule configuration
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = DatasetService()
    try:
        result = await service.get_schedule(
            session=db,
            actor=actor,
            dataset_id=dataset_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    schedule = None
    if result.get("schedule"):
        schedule = ScheduleConfigOut(
            cron=result["schedule"].get("cron"),
            interval_seconds=result["schedule"].get("interval_seconds"),
            active=result["schedule"].get("active", True),
            last_scheduled_at=result["schedule"].get("last_scheduled_at"),
            next_scheduled_at=result["schedule"].get("next_scheduled_at"),
        )

    return DatasetScheduleOut(
        id=UUID(result["id"]),
        name=result["name"],
        schedule=schedule,
        deployment_id=result.get("deployment_id"),
        orchestrator_kind=result.get("orchestrator_kind"),
    )


@router.put("/{dataset_id}/schedule", response_model=DatasetScheduleOut)
async def update_dataset_schedule(
    dataset_id: UUID,
    payload: ScheduleConfigIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetScheduleOut:
    """Update schedule configuration for a dataset.

    Supports:
    - cron: Standard cron expression (e.g., "0 6 * * *" for 6am daily)
    - interval_seconds: Fixed interval in seconds (minimum 60)
    - active: Whether schedule is enabled

    Only one of cron or interval_seconds should be provided.

    The schedule is synced to the orchestrator (Prefect deployment)
    if available.

    Args:
        dataset_id: Dataset resource ID
        payload: Schedule configuration
        actor: Actor context
        db: Database session

    Returns:
        DatasetScheduleOut with updated schedule
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = DatasetService()
    try:
        result = await service.update_schedule(
            session=db,
            actor=actor,
            dataset_id=dataset_id,
            schedule={
                "cron": payload.cron,
                "interval_seconds": payload.interval_seconds,
                "active": payload.active,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    schedule = None
    if result.get("schedule"):
        schedule = ScheduleConfigOut(
            cron=result["schedule"].get("cron"),
            interval_seconds=result["schedule"].get("interval_seconds"),
            active=result["schedule"].get("active", True),
        )

    return DatasetScheduleOut(
        id=UUID(result["id"]),
        name=result["name"],
        schedule=schedule,
        deployment_id=result.get("deployment_id"),
        orchestrator_kind=result.get("orchestrator_kind"),
    )


@router.delete("/{dataset_id}/schedule", response_model=DatasetScheduleOut)
async def delete_dataset_schedule(
    dataset_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DatasetScheduleOut:
    """Remove schedule from a dataset.

    Disables the schedule but keeps the deployment for manual triggers.

    Args:
        dataset_id: Dataset resource ID
        actor: Actor context
        db: Database session

    Returns:
        DatasetScheduleOut with schedule set to None
    """
    resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = DatasetService()
    try:
        result = await service.delete_schedule(
            session=db,
            actor=actor,
            dataset_id=dataset_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return DatasetScheduleOut(
        id=UUID(result["id"]),
        name=result["name"],
        schedule=None,
        deployment_id=result.get("deployment_id"),
        orchestrator_kind=result.get("orchestrator_kind"),
    )
