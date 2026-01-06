"""Notification Management API.

Endpoints for managing user notifications.
Notifications are created by the outbox worker when activities
match user subscriptions.
"""

from __future__ import annotations

from typing import Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.pagination import decode_cursor, encode_cursor
from apps.api.schemas import (
    NotificationMarkAllReadOut,
    NotificationMarkRead,
    NotificationOut,
    NotificationPage,
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
)
from libs.core.events import build_activity_event
from libs.core.rbac.models import ActorContext
from libs.db.models.activity import Activity
from libs.db.models.identity import Principal
from libs.db.models.notification import Notification, NotificationPreference, utcnow
from libs.db.models.resource import Resource

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    unread_only: bool = Query(
        default=False, description="If true, only return unread notifications"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> NotificationPage:
    """List notifications for the current user.

    Returns notifications with embedded activity events.
    """
    # Base query - user's own notifications only
    query = select(Notification).where(
        Notification.tenant_id == actor.tenant_id,
        Notification.principal_id == actor.id,
    )

    if unread_only:
        query = query.where(Notification.read_at.is_(None))

    # Apply cursor-based pagination
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Notification.created_at < cursor_time,
                and_(
                    Notification.created_at == cursor_time,
                    Notification.id < cursor_id,
                ),
            )
        )

    # Order by created_at desc (most recent first)
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc())
    query = query.limit(limit + 1)

    result = await db.scalars(query)
    rows = list(result.all())

    # Determine next cursor
    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    # Get unread count
    unread_count_result = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == actor.tenant_id,
            Notification.principal_id == actor.id,
            Notification.read_at.is_(None),
        )
    )
    unread_count = unread_count_result or 0

    # Hydrate activity events
    activity_ids = [row.activity_id for row in rows]
    activity_map: Dict[UUID, Activity] = {}
    if activity_ids:
        activity_result = await db.scalars(
            select(Activity).where(Activity.id.in_(activity_ids))
        )
        activity_map = {a.id: a for a in activity_result.all()}

    # Build response with hydrated activities
    principal_cache: Dict[UUID, Principal] = {}
    resource_cache: Dict[UUID, Resource] = {}

    items = []
    for row in rows:
        activity_event = None
        if row.activity_id in activity_map:
            activity = activity_map[row.activity_id]
            activity_event = await build_activity_event(
                db,
                activity,
                principal_cache=principal_cache,
                resource_cache=resource_cache,
            )

        items.append(
            NotificationOut(
                id=row.id,
                tenant_id=row.tenant_id,
                principal_id=row.principal_id,
                activity_id=row.activity_id,
                activity=activity_event,
                created_at=row.created_at,
                read_at=row.read_at,
            )
        )

    return NotificationPage(
        items=items, next_cursor=next_cursor, unread_count=unread_count
    )


@router.patch("/{notification_id}", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: UUID,
    body: NotificationMarkRead,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> NotificationOut:
    """Mark a notification as read or unread."""
    result = await db.scalars(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == actor.tenant_id,
            Notification.principal_id == actor.id,
        )
    )
    notification = result.first()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    # Update read status
    if body.read:
        notification.read_at = utcnow()
    else:
        notification.read_at = None

    await db.commit()
    await db.refresh(notification)

    # Hydrate activity
    activity_event = None
    if notification.activity_id:
        activity_result = await db.scalars(
            select(Activity).where(Activity.id == notification.activity_id)
        )
        activity = activity_result.first()
        if activity:
            principal_cache: Dict[UUID, Principal] = {}
            resource_cache: Dict[UUID, Resource] = {}
            activity_event = await build_activity_event(
                db,
                activity,
                principal_cache=principal_cache,
                resource_cache=resource_cache,
            )

    return NotificationOut(
        id=notification.id,
        tenant_id=notification.tenant_id,
        principal_id=notification.principal_id,
        activity_id=notification.activity_id,
        activity=activity_event,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


@router.post("/mark-all-read", response_model=NotificationMarkAllReadOut)
async def mark_all_notifications_read(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> NotificationMarkAllReadOut:
    """Mark all unread notifications as read."""
    # Count how many we're marking
    count_result = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == actor.tenant_id,
            Notification.principal_id == actor.id,
            Notification.read_at.is_(None),
        )
    )
    count = count_result or 0

    if count > 0:
        # Update all unread notifications
        await db.execute(
            update(Notification)
            .where(
                Notification.tenant_id == actor.tenant_id,
                Notification.principal_id == actor.id,
                Notification.read_at.is_(None),
            )
            .values(read_at=utcnow())
        )
        await db.commit()

    return NotificationMarkAllReadOut(marked_count=count)


@router.get("/unread-count")
async def get_unread_count(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the count of unread notifications."""
    result = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == actor.tenant_id,
            Notification.principal_id == actor.id,
            Notification.read_at.is_(None),
        )
    )
    return {"unread_count": result or 0}


@router.get("/preferences", response_model=NotificationPreferenceOut)
async def get_notification_preferences(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceOut:
    """Get notification preferences for the current user.

    Returns user's notification preferences. If no preferences exist,
    returns defaults (filter_mode="mutations", muted=False).
    """
    result = await db.scalars(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == actor.tenant_id,
            NotificationPreference.principal_id == actor.id,
        )
    )
    pref = result.first()

    if pref is None:
        # Return defaults without creating a record
        from uuid import uuid4

        return NotificationPreferenceOut(
            id=uuid4(),  # Placeholder - not persisted
            tenant_id=actor.tenant_id,
            principal_id=actor.id,
            filter_mode="mutations",
            custom_actions=[],
            muted=False,
            updated_at=utcnow(),
        )

    return NotificationPreferenceOut.model_validate(pref)


@router.put("/preferences", response_model=NotificationPreferenceOut)
async def update_notification_preferences(
    body: NotificationPreferenceUpdate,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferenceOut:
    """Update notification preferences for the current user.

    - filter_mode: "all" (all activities), "mutations" (create/update/delete only),
                   or "custom" (user-defined patterns)
    - custom_actions: List of action patterns (e.g., ["resource.*", "chat.*"])
    - muted: If true, suppress all notifications
    """
    # Validate filter_mode
    valid_modes = {"all", "mutations", "custom"}
    if body.filter_mode is not None and body.filter_mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filter_mode. Must be one of: {', '.join(valid_modes)}",
        )

    # Get or create preference record
    result = await db.scalars(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == actor.tenant_id,
            NotificationPreference.principal_id == actor.id,
        )
    )
    pref = result.first()

    if pref is None:
        # Create new preference record
        from uuid import uuid4

        pref = NotificationPreference(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=actor.id,
            filter_mode=body.filter_mode or "mutations",
            custom_actions=body.custom_actions or [],
            muted=body.muted if body.muted is not None else False,
            updated_at=utcnow(),
        )
        db.add(pref)
    else:
        # Update existing
        if body.filter_mode is not None:
            pref.filter_mode = body.filter_mode
        if body.custom_actions is not None:
            pref.custom_actions = body.custom_actions
        if body.muted is not None:
            pref.muted = body.muted
        pref.updated_at = utcnow()

    await db.commit()
    await db.refresh(pref)

    return NotificationPreferenceOut.model_validate(pref)
