from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.events import build_activity_event
from libs.db.models.activity import Activity, Outbox

T = TypeVar("T")

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class ActivityEnvelope(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    actor_principal_id: UUID
    resource_id: UUID
    resource_type: str
    action: str
    target_principal_id: Optional[UUID] = None
    visibility: str = "resource"
    payload: Dict[str, Any] = Field(default_factory=dict)
    delivery_channels: list[str] = Field(default_factory=list)
    correlation_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utcnow)

async def _get_activity_by_idempotency(
    session: AsyncSession,
    tenant_id: UUID,
    correlation_id: UUID,
    action: str,
    resource_id: UUID,
) -> Optional[Activity]:
    stmt = select(Activity).where(
        Activity.tenant_id == tenant_id,
        Activity.correlation_id == correlation_id,
        Activity.action == action,
        Activity.resource_id == resource_id,
    )
    result = await session.scalars(stmt)
    return result.first()

async def record_activity(session: AsyncSession, envelope: ActivityEnvelope) -> Activity:
    existing = await _get_activity_by_idempotency(
        session,
        envelope.tenant_id,
        envelope.correlation_id,
        envelope.action,
        envelope.resource_id,
    )
    if existing:
        return existing

    activity = Activity(
        tenant_id=envelope.tenant_id,
        actor_principal_id=envelope.actor_principal_id,
        resource_id=envelope.resource_id,
        resource_type=envelope.resource_type,
        action=envelope.action,
        target_principal_id=envelope.target_principal_id,
        visibility=envelope.visibility,
        payload=envelope.payload,
        correlation_id=envelope.correlation_id,
        created_at=envelope.created_at,
    )
    session.add(activity)
    await session.flush()
    return activity

async def enqueue_outbox(
    session: AsyncSession, topic: str, key: str, payload: Dict[str, Any]
) -> Outbox:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict containing tenant_id")

    tenant_id = payload.get("tenant_id")
    if tenant_id is None:
        raise ValueError("payload missing tenant_id for outbox row")
    if isinstance(tenant_id, str):
        tenant_id = UUID(tenant_id)

    outbox = Outbox(
        tenant_id=tenant_id,
        topic=topic,
        key=key,
        payload=payload,
    )
    session.add(outbox)
    await session.flush()
    return outbox

async def record_activity_with_outbox(
    session: AsyncSession,
    envelope: ActivityEnvelope,
    *,
    topic: str = "activity",
) -> Activity:
    existing = await _get_activity_by_idempotency(
        session,
        envelope.tenant_id,
        envelope.correlation_id,
        envelope.action,
        envelope.resource_id,
    )
    if existing:
        return existing
    activity = await record_activity(session, envelope)
    event = await build_activity_event(session, activity)
    outbox_payload = event.model_dump(mode="json")
    await enqueue_outbox(session, topic, str(activity.id), outbox_payload)
    return activity

async def tx_activity(
    session: AsyncSession,
    envelope: ActivityEnvelope,
    fn: Callable[[AsyncSession], Awaitable[T]],
) -> Tuple[Optional[T], Activity]:
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    async with transaction:
        existing = await _get_activity_by_idempotency(
            session,
            envelope.tenant_id,
            envelope.correlation_id,
            envelope.action,
            envelope.resource_id,
        )
        if existing:
            return None, existing

        result = await fn(session)
        activity = await record_activity(session, envelope)
        event = await build_activity_event(session, activity)
        outbox_payload = event.model_dump(mode="json")
        await enqueue_outbox(session, "activity", str(activity.id), outbox_payload)
        return result, activity
