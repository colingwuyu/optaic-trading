from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.pagination import decode_cursor, encode_cursor
from apps.api.schemas import ActivityPage
from libs.core.events import ActivityEventV1, build_activity_event
from libs.core.rbac import authorize
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.activity import Activity
from libs.db.models.identity import Principal
from libs.db.models.resource import Resource
from libs.db.models.subscription import Subscription

router = APIRouter(prefix="/activities", tags=["Activities"])


async def _resource_chain(
    db: AsyncSession,
    tenant_id: UUID,
    resource_id: UUID,
    cache: Dict[UUID, List[UUID]],
) -> List[UUID]:
    if resource_id in cache:
        return cache[resource_id]
    chain: List[UUID] = []
    current_id: Optional[UUID] = resource_id
    while current_id is not None:
        result = await db.scalars(
            select(Resource).where(
                Resource.id == current_id,
                Resource.tenant_id == tenant_id,
            )
        )
        resource = result.first()
        if not resource:
            break
        chain.append(resource.id)
        current_id = resource.parent_id
    cache[resource_id] = chain
    return chain

@router.get("", response_model=ActivityPage)
async def list_activities(
    resource_id: Optional[UUID] = Query(default=None),
    after: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ActivityPage:
    base_query = select(Activity).where(Activity.tenant_id == actor.tenant_id)
    if after is not None:
        base_query = base_query.where(Activity.created_at > after)
    if resource_id:
        base_query = base_query.where(Activity.resource_id == resource_id)

    subscription_result = await db.scalars(
        select(Subscription).where(
            Subscription.tenant_id == actor.tenant_id,
            Subscription.principal_id == actor.id,
            Subscription.revoked_at.is_(None),
        )
    )
    subscriptions = list(subscription_result.all())
    resource_subs = {sub.resource_id for sub in subscriptions if sub.scope == "resource"}
    descendant_subs = {
        sub.resource_id for sub in subscriptions if sub.scope == "descendants"
    }

    if resource_id:
        allowed, _explain = await authorize(
            db, actor.tenant_id, actor.id, resource_id, Permission.VIEW_ACTIVITY_FEED
        )
        if not allowed and resource_id not in resource_subs and resource_id not in descendant_subs:
            raise HTTPException(status_code=403, detail="Forbidden")

    visible: List[ActivityEventV1] = []
    next_cursor: Optional[str] = None
    current_cursor = cursor
    chain_cache: Dict[UUID, List[UUID]] = {}
    authz_cache: Dict[UUID, bool] = {}
    principal_cache: Dict[UUID, Principal] = {}
    resource_cache: Dict[UUID, Resource] = {}

    while len(visible) < limit:
        query = base_query
        if current_cursor:
            cursor_time, cursor_id = decode_cursor(current_cursor)
            query = query.where(
                or_(
                    Activity.created_at < cursor_time,
                    and_(
                        Activity.created_at == cursor_time,
                        Activity.id < cursor_id,
                    ),
                )
            )

        query = query.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit + 1)
        result = await db.scalars(query)
        batch = result.all()
        if not batch:
            break

        last_visible = None
        for activity in batch:
            if activity.target_principal_id == actor.id:
                event = await build_activity_event(
                    db,
                    activity,
                    principal_cache=principal_cache,
                    resource_cache=resource_cache,
                )
                visible.append(event)
                last_visible = activity
                if len(visible) == limit:
                    break
                continue

            is_subscribed = False
            if activity.resource_id in resource_subs:
                is_subscribed = True
            elif descendant_subs:
                chain = await _resource_chain(
                    db, actor.tenant_id, activity.resource_id, chain_cache
                )
                if any(resource_id in descendant_subs for resource_id in chain):
                    is_subscribed = True

            if is_subscribed:
                event = await build_activity_event(
                    db,
                    activity,
                    principal_cache=principal_cache,
                    resource_cache=resource_cache,
                )
                visible.append(event)
                last_visible = activity
                if len(visible) == limit:
                    break
                continue

            if activity.resource_id not in authz_cache:
                allowed, _explain = await authorize(
                    db,
                    actor.tenant_id,
                    actor.id,
                    activity.resource_id,
                    Permission.VIEW_ACTIVITY_FEED,
                )
                authz_cache[activity.resource_id] = allowed
            if authz_cache[activity.resource_id]:
                event = await build_activity_event(
                    db,
                    activity,
                    principal_cache=principal_cache,
                    resource_cache=resource_cache,
                )
                visible.append(event)
                last_visible = activity
                if len(visible) == limit:
                    break

        if len(visible) == limit and last_visible is not None:
            next_cursor = encode_cursor(last_visible.created_at, last_visible.id)
            break

        if len(batch) < limit + 1:
            break

        current_cursor = encode_cursor(batch[-1].created_at, batch[-1].id)

    return ActivityPage(items=visible, next_cursor=next_cursor)
