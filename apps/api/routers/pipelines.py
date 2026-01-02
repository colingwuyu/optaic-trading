"""Pipelines API Router.

Provides endpoints for:
- Submitting pipeline definitions
- Deploying definitions
- Creating pipeline instances
- Triggering pipeline runs
- Listing definitions and instances
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    PipelineDefinitionCreate,
    PipelineDefinitionOut,
    PipelineInstanceCreate,
    PipelineInstanceOut,
    PipelineRunOut,
)
from apps.api.services import PipelineService
from libs.core.rbac.models import ActorContext, Permission

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


# --- Definition Endpoints ---


@router.post("/definitions", response_model=PipelineDefinitionOut, status_code=201)
async def submit_definition(
    payload: PipelineDefinitionCreate = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PipelineDefinitionOut:
    """Submit a new pipeline definition.

    Creates a PipelineDefinition resource in draft status.
    Must be deployed before it can be used to create instances.

    Args:
        payload: Definition details including code_ref
        actor: Actor context
        db: Database session

    Returns:
        Created definition info
    """
    # Check permission on parent resource
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    service = PipelineService()
    try:
        result = await service.submit_definition(
            session=db,
            actor=actor,
            name=payload.name,
            code_ref=payload.code_ref,
            category=payload.category,
            parent_id=payload.parent_id,
            interface_spec=payload.interface_spec,
            input_schema=payload.input_schema,
            output_schema=payload.output_schema,
            parameters_schema=payload.parameters_schema,
            guardrail_contracts=payload.guardrail_contracts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PipelineDefinitionOut(
        id=UUID(result["id"]),
        name=result["name"],
        code_ref=result["code_ref"],
        category=result["category"],
        status=result["status"],
    )


@router.post("/definitions/{definition_id}/deploy", response_model=PipelineDefinitionOut)
async def deploy_definition(
    definition_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PipelineDefinitionOut:
    """Deploy a pipeline definition.

    Changes status from draft to active, allowing instance creation.

    Args:
        definition_id: Pipeline definition resource ID
        actor: Actor context
        db: Database session

    Returns:
        Deployed definition info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, definition_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = PipelineService()
    try:
        result = await service.deploy_definition(
            session=db,
            actor=actor,
            definition_id=definition_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PipelineDefinitionOut(
        id=UUID(result["id"]),
        name=result["name"],
        code_ref=result["code_ref"],
        category=result.get("category", "unknown"),
        status=result["status"],
    )


@router.get("/definitions", response_model=List[PipelineDefinitionOut])
async def list_definitions(
    category: Optional[str] = Query(default=None, examples=["etl"]),
    status: Optional[str] = Query(default=None, examples=["active"]),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[PipelineDefinitionOut]:
    """List pipeline definitions.

    Args:
        category: Optional category filter
        status: Optional status filter (draft, active)
        limit: Maximum results
        actor: Actor context
        db: Database session

    Returns:
        List of definition info
    """
    service = PipelineService()
    results = await service.list_definitions(
        session=db,
        actor=actor,
        category=category,
        status=status,
        limit=limit,
    )

    return [
        PipelineDefinitionOut(
            id=UUID(r["id"]),
            name=r["name"],
            code_ref=r["code_ref"],
            category=r["category"],
            status=r["status"],
        )
        for r in results
    ]


# --- Instance Endpoints ---


@router.post("/instances", response_model=PipelineInstanceOut, status_code=201)
async def create_instance(
    payload: PipelineInstanceCreate = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PipelineInstanceOut:
    """Create a pipeline instance from a definition.

    Args:
        payload: Instance details including definition_id
        actor: Actor context
        db: Database session

    Returns:
        Created instance info
    """
    # Check permission on parent resource
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    service = PipelineService()
    try:
        result = await service.create_instance(
            session=db,
            actor=actor,
            name=payload.name,
            definition_id=payload.definition_id,
            parent_id=payload.parent_id,
            config=payload.config,
            schedule=payload.schedule,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PipelineInstanceOut(
        id=UUID(result["id"]),
        name=result["name"],
        definition_id=UUID(result["definition_id"]),
        code_ref=result["code_ref"],
        status=result["status"],
    )


@router.post("/instances/{instance_id}/run", response_model=PipelineRunOut)
async def trigger_run(
    instance_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> PipelineRunOut:
    """Trigger a pipeline run.

    Args:
        instance_id: Pipeline instance resource ID
        actor: Actor context
        db: Database session

    Returns:
        Run submission info
    """
    resource = await get_resource_or_404(db, actor.tenant_id, instance_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = PipelineService()
    try:
        result = await service.trigger_run(
            session=db,
            actor=actor,
            instance_id=instance_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PipelineRunOut(
        instance_id=UUID(result["instance_id"]),
        code_ref=result["code_ref"],
        status=result["status"],
        message=result["message"],
    )


@router.get("/instances", response_model=List[PipelineInstanceOut])
async def list_instances(
    parent_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(default=None, examples=["idle", "running"]),
    limit: int = Query(default=50, ge=1, le=200),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[PipelineInstanceOut]:
    """List pipeline instances.

    Args:
        parent_id: Optional parent resource filter
        status: Optional status filter (idle, running)
        limit: Maximum results
        actor: Actor context
        db: Database session

    Returns:
        List of instance info
    """
    service = PipelineService()
    results = await service.list_instances(
        session=db,
        actor=actor,
        parent_id=parent_id,
        status=status,
        limit=limit,
    )

    return [
        PipelineInstanceOut(
            id=UUID(r["id"]),
            name=r["name"],
            definition_id=UUID(r["definition_id"]),
            code_ref="",  # Not returned from list
            status=r["status"],
        )
        for r in results
    ]
