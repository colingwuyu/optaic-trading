from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, get_guardrails_engine, reset_session
from apps.api.pagination import decode_cursor, encode_cursor
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    ResourceCopy,
    ResourceCopyOut,
    ResourceCreate,
    ResourceMove,
    ResourceOut,
    ResourcePage,
    ResourceTree,
    ResourceUpdate,
)
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.core.versioning import initialize_versioning
from libs.db.models.resource import Resource, ResourceEdge
from optaic.guardrails.runtime.context import GuardrailsContext
from optaic.guardrails.runtime.engine import GuardrailsBlocked, GuardrailsEngine
from fastapi import HTTPException

router = APIRouter(prefix="/resources", tags=["Resources"])


@router.post(
    "",
    response_model=ResourceOut,
    status_code=201,
)
async def create_resource(
    payload: ResourceCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create resource",
                "value": {
                    "type": "Project",
                    "parent_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1",
                    "name": "Roadmap",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    guardrails: GuardrailsEngine = Depends(get_guardrails_engine),
) -> ResourceOut:
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    resource_id = uuid4()

    async def domain_fn(session: AsyncSession) -> Resource:
        resource = Resource(
            id=resource_id,
            tenant_id=actor.tenant_id,
            type=payload.type,
            parent_id=payload.parent_id,
            owner_principal_id=actor.id,
            name=payload.name,
            status="active",
            metadata_json=payload.metadata,
        )
        session.add(resource)
        await session.flush()
        await initialize_versioning(session, resource, actor.id)
        return resource

        return resource

    # Guardrails Validation
    try:
        context = GuardrailsContext(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            space_kind=None,  # Not known yet or inherit?
            subspace_kind=None,
            action="create",
        )
        await guardrails.validate_at_gate(
            db=db,
            scope="resource",
            target_id=str(resource_id),
            resource_id=str(resource_id),
            context=context,
            target_snapshot=payload.model_dump(mode="json"),
        )
    except GuardrailsBlocked as exc:
        await db.commit()  # Persist the block event/report
        raise HTTPException(status_code=403, detail=str(exc))

    await reset_session(db)

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=payload.type,
        action="resource.created",
        payload={"parent_id": str(payload.parent_id), "name": payload.name},
    )
    resource, _activity = await tx_activity(db, envelope, domain_fn)
    return ResourceOut.model_validate(resource)


@router.get("/{resource_id}", response_model=ResourceOut)
async def get_resource(
    resource_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ResourceOut:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)
    return ResourceOut.model_validate(resource)


@router.get("/{resource_id}/children", response_model=ResourcePage)
async def list_children(
    resource_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ResourcePage:
    parent = await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, parent.id)

    query = select(Resource).where(
        Resource.tenant_id == actor.tenant_id,
        Resource.parent_id == resource_id,
    )
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Resource.created_at > cursor_time,
                and_(
                    Resource.created_at == cursor_time,
                    Resource.id > cursor_id,
                ),
            )
        )
    query = query.order_by(Resource.created_at.asc(), Resource.id.asc()).limit(
        limit + 1
    )

    result = await db.scalars(query)
    rows = result.all()
    items = [ResourceOut.model_validate(resource) for resource in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and items:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return ResourcePage(items=items, next_cursor=next_cursor)


async def _build_tree(
    db: AsyncSession, tenant_id: UUID, resource_id: UUID, depth: int
) -> ResourceTree:
    resource = await get_resource_or_404(db, tenant_id, resource_id)
    node = ResourceTree(resource=ResourceOut.model_validate(resource))
    if depth <= 0:
        return node

    result = await db.scalars(
        select(Resource)
        .where(Resource.tenant_id == tenant_id, Resource.parent_id == resource_id)
        .order_by(Resource.created_at.asc(), Resource.id.asc())
    )
    children = result.all()
    for child in children:
        node.children.append(await _build_tree(db, tenant_id, child.id, depth - 1))
    return node


@router.get("/{resource_id}/tree", response_model=ResourceTree)
async def get_tree(
    resource_id: UUID,
    depth: int = Query(default=2, ge=0, le=5),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ResourceTree:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)
    return await _build_tree(db, actor.tenant_id, resource.id, depth)


@router.patch("/{resource_id}", response_model=ResourceOut)
async def update_resource(
    resource_id: UUID,
    payload: ResourceUpdate = Body(
        ...,
        examples={
            "default": {
                "summary": "Update resource",
                "value": {"name": "New name", "metadata": {"break_inheritance": True}},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    guardrails: GuardrailsEngine = Depends(get_guardrails_engine),
) -> ResourceOut:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    changes: dict[str, object] = {}
    if payload.name is not None and payload.name != resource.name:
        changes["name"] = {"from": resource.name, "to": payload.name}
    if payload.status is not None and payload.status != resource.status:
        changes["status"] = {"from": resource.status, "to": payload.status}
    if payload.metadata is not None and payload.metadata != resource.metadata_json:
        changes["metadata"] = {"from": resource.metadata_json, "to": payload.metadata}

    if not changes:
        return ResourceOut.model_validate(resource)

    resource_id = resource.id
    resource_type = resource.type
    resource_id = resource.id
    resource_type = resource.type

    # Guardrails Validation
    try:
        context = GuardrailsContext(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            space_kind=resource.space_kind,
            subspace_kind=resource.subspace_kind,
            action="update",
        )
        await guardrails.validate_at_gate(
            db=db,
            scope="resource",
            target_id=str(resource_id),
            resource_id=str(resource_id),
            context=context,
            target_snapshot={"changes": changes},
        )
    except GuardrailsBlocked as exc:
        await db.commit()  # Persist the block event/report
        raise HTTPException(status_code=403, detail=str(exc))

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Resource:
        target = await get_resource_or_404(session, actor.tenant_id, resource_id)
        if payload.name is not None:
            target.name = payload.name
        if payload.status is not None:
            target.status = payload.status
        if payload.metadata is not None:
            target.metadata_json = payload.metadata
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="resource.updated",
        payload={"changes": changes},
    )
    updated, _activity = await tx_activity(db, envelope, domain_fn)
    return ResourceOut.model_validate(updated)


@router.post("/{resource_id}/move", response_model=ResourceOut)
async def move_resource(
    resource_id: UUID,
    payload: ResourceMove = Body(
        ...,
        examples={
            "default": {
                "summary": "Move resource",
                "value": {"new_parent_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ResourceOut:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    new_parent = await get_resource_or_404(db, actor.tenant_id, payload.new_parent_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)
    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, new_parent.id)

    old_parent_id = resource.parent_id
    resource_id = resource.id
    resource_type = resource.type

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Resource:
        target = await get_resource_or_404(session, actor.tenant_id, resource_id)
        target.parent_id = payload.new_parent_id
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="resource.moved",
        payload={
            "from_parent": str(old_parent_id),
            "to_parent": str(payload.new_parent_id),
        },
    )
    moved, _activity = await tx_activity(db, envelope, domain_fn)
    return ResourceOut.model_validate(moved)


@router.delete("/{resource_id}", response_model=ResourceOut)
async def delete_resource(
    resource_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    guardrails: GuardrailsEngine = Depends(get_guardrails_engine),
) -> ResourceOut:
    resource = await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_DELETE, resource.id)

    resource_id = resource.id
    resource_type = resource.type

    # Guardrails Validation
    try:
        context = GuardrailsContext(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            # Assume resource doesn't have space/subspace fields yet on the model or we need to fetch them?
            # Existing specific resource models (Project/Space) might have them, but 'Resource' is generic base.
            # For now, pass None or try to get from metadata?
            # The context definition expects space_kind/subspace_kind.
            # Let's assume passed as None or derived if possible.
            space_kind=None,
            subspace_kind=None,
            action="delete",
        )
        await guardrails.validate_at_gate(
            db=db,
            scope="resource",
            target_id=str(resource_id),
            resource_id=str(resource_id),
            context=context,
            target_snapshot={},
        )
    except GuardrailsBlocked as exc:
        await db.commit()  # Persist the block event/report
        raise HTTPException(status_code=403, detail=str(exc))

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Resource:
        target = await get_resource_or_404(session, actor.tenant_id, resource_id)
        target.status = "deleted"
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="resource.deleted",
        payload={"soft": True},
    )
    deleted, _activity = await tx_activity(db, envelope, domain_fn)
    return ResourceOut.model_validate(deleted)


@router.post("/{resource_id}/copy", response_model=ResourceCopyOut, status_code=201)
async def copy_resource(
    resource_id: UUID,
    payload: ResourceCopy = Body(
        ...,
        examples={
            "default": {
                "summary": "Copy resource",
                "value": {
                    "target_parent_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1",
                    "new_name": "My Copy",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ResourceCopyOut:
    """Copy a resource to a new location.

    Creates a copy of the source resource under the target parent.
    The copy will have:
    - A new UUID
    - The copier as owner
    - A derived_from lineage edge to the source

    Requires:
    - RESOURCE_READ on the source resource
    - RESOURCE_CREATE_CHILD on the target parent

    This is primarily used to copy plugin definitions from System Space
    to user projects.
    """
    # Get source resource and verify read permission
    source = await get_resource_or_404(db, actor.tenant_id, resource_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, source.id)

    # Get target parent and verify create permission
    target_parent = await get_resource_or_404(
        db, actor.tenant_id, payload.target_parent_id
    )
    await authorize_or_403(
        db, actor, Permission.RESOURCE_CREATE_CHILD, target_parent.id
    )

    source_id = source.id
    source_type = source.type
    source_name = source.name
    source_metadata = source.metadata_json.copy() if source.metadata_json else {}

    new_id = uuid4()
    new_name = payload.new_name or source_name

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Resource:
        # Create the copy
        copy = Resource(
            id=new_id,
            tenant_id=actor.tenant_id,
            type=source_type,
            parent_id=payload.target_parent_id,
            owner_principal_id=actor.id,
            name=new_name,
            status="active",
            metadata_json={
                **source_metadata,
                "copied_from": str(source_id),
            },
        )
        session.add(copy)
        await session.flush()

        # Create derived_from lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=new_id,  # The copy points to the source
            dst_resource_id=source_id,
            edge_type="derived_from",
        )
        session.add(edge)

        # Initialize versioning for the copy
        await initialize_versioning(session, copy, actor.id)
        return copy

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=new_id,
        resource_type=source_type,
        action="resource.copied",
        payload={
            "source_id": str(source_id),
            "source_name": source_name,
            "target_parent_id": str(payload.target_parent_id),
            "new_name": new_name,
        },
    )
    copy, _activity = await tx_activity(db, envelope, domain_fn)

    return ResourceCopyOut(
        id=copy.id,
        source_id=source_id,
        name=copy.name,
        type=copy.type,
        parent_id=copy.parent_id,
        owner_principal_id=copy.owner_principal_id,
        derived_from_id=source_id,
    )
