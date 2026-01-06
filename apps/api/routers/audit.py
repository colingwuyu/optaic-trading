"""Audit Log Query API.

Admin-only endpoint for querying the complete audit log.
Unlike /activities which filters by RBAC, /audit-logs provides
full audit trail access for administrators.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.pagination import decode_cursor, encode_cursor
from apps.api.schemas import AuditLogEntry, AuditLogPage
from libs.core.rbac.models import ActorContext
from libs.db.models.notification import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    actor_principal_id: Optional[UUID] = Query(
        default=None, description="Filter by actor who performed the action"
    ),
    resource_id: Optional[UUID] = Query(
        default=None, description="Filter by resource ID"
    ),
    action: Optional[str] = Query(
        default=None, description="Filter by action type (e.g., resource.created)"
    ),
    after: Optional[datetime] = Query(
        default=None, description="Return entries after this timestamp"
    ),
    before: Optional[datetime] = Query(
        default=None, description="Return entries before this timestamp"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    """Query audit logs with filtering.

    This endpoint is admin-only and returns the complete audit trail.
    Filters can be combined to narrow results.

    Note: This queries the audit_log table which contains denormalized
    activity envelopes for efficient searching. The envelope contains
    the full activity event as recorded at the time of processing.
    """
    # TODO: Add proper admin role check via RBAC
    # For now, any authenticated user with tenant access can query
    # In production, this should check for AUDIT_ADMIN role

    query = select(AuditLog).where(AuditLog.tenant_id == actor.tenant_id)

    # Apply filters based on envelope JSON fields
    if actor_principal_id:
        # Filter by actor in envelope
        query = query.where(
            AuditLog.envelope["actor"]["principal_id"].as_string()
            == str(actor_principal_id)
        )

    if resource_id:
        # Filter by resource in envelope
        query = query.where(
            AuditLog.envelope["resource"]["resource_id"].as_string() == str(resource_id)
        )

    if action:
        # Filter by action in envelope
        query = query.where(AuditLog.envelope["action"].as_string() == action)

    if after:
        query = query.where(AuditLog.processed_at > after)

    if before:
        query = query.where(AuditLog.processed_at < before)

    # Apply cursor-based pagination
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        query = query.where(
            or_(
                AuditLog.processed_at < cursor_time,
                and_(
                    AuditLog.processed_at == cursor_time,
                    AuditLog.id < cursor_id,
                ),
            )
        )

    # Order by processed_at desc (most recent first)
    query = query.order_by(AuditLog.processed_at.desc(), AuditLog.id.desc())
    query = query.limit(limit + 1)

    result = await db.scalars(query)
    rows = list(result.all())

    # Determine next cursor
    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.processed_at, last.id)

    items = [
        AuditLogEntry(
            id=row.id,
            tenant_id=row.tenant_id,
            activity_id=row.activity_id,
            envelope=row.envelope,
            processed_at=row.processed_at,
        )
        for row in rows
    ]

    return AuditLogPage(items=items, next_cursor=next_cursor)


@router.get("/count")
async def count_audit_logs(
    actor_principal_id: Optional[UUID] = Query(default=None),
    resource_id: Optional[UUID] = Query(default=None),
    action: Optional[str] = Query(default=None),
    after: Optional[datetime] = Query(default=None),
    before: Optional[datetime] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Count audit log entries matching the filters."""
    query = select(func.count(AuditLog.id)).where(AuditLog.tenant_id == actor.tenant_id)

    if actor_principal_id:
        query = query.where(
            AuditLog.envelope["actor"]["principal_id"].as_string()
            == str(actor_principal_id)
        )

    if resource_id:
        query = query.where(
            AuditLog.envelope["resource"]["resource_id"].as_string() == str(resource_id)
        )

    if action:
        query = query.where(AuditLog.envelope["action"].as_string() == action)

    if after:
        query = query.where(AuditLog.processed_at > after)

    if before:
        query = query.where(AuditLog.processed_at < before)

    result = await db.scalar(query)
    return {"count": result or 0}
