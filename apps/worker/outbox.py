from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, Iterable, Optional
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import libs.db.models  # noqa: F401
from libs.core.settings import get_settings
from libs.db.models.activity import Outbox
from libs.db.models.notification import AuditLog, Notification
from libs.db.models.rbac import RoleBinding
from libs.db.models.resource import Resource
from libs.db.models.subscription import Subscription

Handler = Callable[[AsyncSession, Outbox], Awaitable[None]]

_CHAT_ACTION_PREFIXES = ("message.", "receipt.")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_uuid(value: object) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class CentrifugoPublisher:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        timeout: float = 5.0,
        max_retries: int = 5,
        base_delay: float = 0.25,
    ) -> None:
        api_url = api_url.rstrip("/")
        self.api_url = api_url if api_url.endswith("/api") else f"{api_url}/api"
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.logger = structlog.get_logger("worker.centrifugo")

    async def publish_channels(self, channels: Iterable[str], data: Dict[str, object]) -> None:
        channels_list = list(channels)
        if not channels_list:
            return

        headers = {"Authorization": f"apikey {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            for channel in channels_list:
                await self._publish_channel(client, channel, data)

    async def _publish_channel(
        self,
        client: httpx.AsyncClient,
        channel: str,
        data: Dict[str, object],
    ) -> None:
        payload = {"method": "publish", "params": {"channel": channel, "data": data}}
        for attempt in range(self.max_retries):
            try:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                body = response.json()
                if isinstance(body, dict) and body.get("error"):
                    raise RuntimeError(body["error"])
                return
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                if attempt == self.max_retries - 1:
                    self.logger.error(
                        "centrifugo.publish_failed",
                        channel=channel,
                        attempts=self.max_retries,
                        error=str(exc),
                    )
                    raise
                delay = self.base_delay * (2**attempt)
                self.logger.warning(
                    "centrifugo.publish_retry",
                    channel=channel,
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)


def _activity_channels(payload: Dict[str, object], tenant_id: UUID) -> list[str]:
    channels: set[str] = set()
    tenant_part = str(tenant_id)

    targets = payload.get("targets")
    if isinstance(targets, dict):
        for principal_id in targets.get("user_inbox") or []:
            principal_uuid = _coerce_uuid(principal_id)
            if principal_uuid is not None:
                channels.add(f"t:{tenant_part}:u:{principal_uuid}")
        for resource_id in targets.get("resource_channels") or []:
            resource_uuid = _coerce_uuid(resource_id)
            if resource_uuid is not None:
                channels.add(f"t:{tenant_part}:r:{resource_uuid}")
        for channel_id in targets.get("chat_channels") or []:
            channel_uuid = _coerce_uuid(channel_id)
            if channel_uuid is not None:
                channels.add(f"t:{tenant_part}:c:{channel_uuid}")

    if channels:
        return list(channels)

    target_principal_id = _coerce_uuid(payload.get("target_principal_id"))
    if target_principal_id is not None:
        channels.add(f"t:{tenant_part}:u:{target_principal_id}")

    resource = payload.get("resource") or {}
    if not isinstance(resource, dict):
        resource = {}
    resource_id = _coerce_uuid(resource.get("resource_id"))
    if resource_id is not None:
        channels.add(f"t:{tenant_part}:r:{resource_id}")

    action = str(payload.get("action") or "")
    if action.startswith(_CHAT_ACTION_PREFIXES):
        event_payload = payload.get("payload") or {}
        channel_id = None
        if isinstance(event_payload, dict):
            channel_id = _coerce_uuid(event_payload.get("channel_id"))
        if channel_id is None and resource.get("resource_type") == "Channel":
            channel_id = resource_id
        if channel_id is not None:
            channels.add(f"t:{tenant_part}:c:{channel_id}")

    return list(channels)


async def _resource_chain(
    session: AsyncSession,
    tenant_id: UUID,
    resource_id: UUID,
) -> list[UUID]:
    chain: list[UUID] = []
    current_id: Optional[UUID] = resource_id
    while current_id is not None:
        result = await session.scalars(
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
    return chain


async def _subscription_watchers(
    session: AsyncSession,
    tenant_id: UUID,
    resource_id: UUID,
) -> set[UUID]:
    scope_ids = await _resource_chain(session, tenant_id, resource_id)
    if not scope_ids:
        return set()

    result = await session.scalars(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id,
            Subscription.revoked_at.is_(None),
            Subscription.resource_id.in_(scope_ids),
        )
    )
    watchers: set[UUID] = set()
    for sub in result.all():
        if sub.scope == "resource" and sub.resource_id != resource_id:
            continue
        watchers.add(sub.principal_id)
    return watchers


async def _channel_members(
    session: AsyncSession,
    tenant_id: UUID,
    channel_id: UUID,
) -> set[UUID]:
    result = await session.scalars(
        select(RoleBinding.principal_id).where(
            RoleBinding.tenant_id == tenant_id,
            RoleBinding.scope_resource_id == channel_id,
            RoleBinding.revoked_at.is_(None),
        )
    )
    return {principal_id for principal_id in result.all()}


def build_activity_handler(publisher: Optional[CentrifugoPublisher]) -> Handler:
    async def handle_activity_outbox(session: AsyncSession, row: Outbox) -> None:
        payload = row.payload or {}
        if not isinstance(payload, dict):
            raise ValueError("outbox payload must be a dict")
        tenant_id = _coerce_uuid(payload.get("tenant_id")) or row.tenant_id
        activity_id = _coerce_uuid(payload.get("event_id")) or _coerce_uuid(row.key)
        if activity_id is None:
            raise ValueError("outbox key is not a valid activity id")

        target_principal_id = _coerce_uuid(payload.get("target_principal_id"))
        if target_principal_id is not None:
            stmt = pg_insert(Notification).values(
                id=uuid4(),
                tenant_id=tenant_id,
                principal_id=target_principal_id,
                activity_id=activity_id,
                created_at=utcnow(),
            )
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["tenant_id", "principal_id", "activity_id"]
            )
            await session.execute(stmt)

        audit = AuditLog(
            tenant_id=tenant_id,
            activity_id=activity_id,
            envelope=payload,
            processed_at=utcnow(),
        )
        session.add(audit)
        await session.flush()

        if publisher is not None:
            data = dict(payload)
            channels = set(_activity_channels(payload, tenant_id))

            resource = payload.get("resource") or {}
            if not isinstance(resource, dict):
                resource = {}
            resource_id = _coerce_uuid(resource.get("resource_id"))
            watchers: set[UUID] = set()
            if resource_id is not None:
                watchers |= await _subscription_watchers(session, tenant_id, resource_id)

            action = str(payload.get("action") or "")
            if action.startswith(_CHAT_ACTION_PREFIXES):
                channel_id = None
                event_payload = payload.get("payload") or {}
                if isinstance(event_payload, dict):
                    channel_id = _coerce_uuid(event_payload.get("channel_id"))
                if channel_id is None and resource.get("resource_type") == "Channel":
                    channel_id = resource_id
                if channel_id is not None:
                    watchers |= await _channel_members(session, tenant_id, channel_id)

            if target_principal_id is not None:
                watchers.discard(target_principal_id)

            for principal_id in watchers:
                channels.add(f"t:{tenant_id}:u:{principal_id}")

            await publisher.publish_channels(channels, data)

    return handle_activity_outbox


def default_handlers(*, publish: bool = True) -> Dict[str, Handler]:
    publisher = None
    if publish:
        settings = get_settings()
        publisher = CentrifugoPublisher(
            api_url=settings.centrifugo_url,
            api_key=settings.centrifugo_api_key,
        )
    return {"activity": build_activity_handler(publisher)}


async def fetch_outbox_batch(
    session: AsyncSession,
    batch_size: int,
    tenant_id: Optional[UUID] = None,
    topic: Optional[str] = None,
) -> list[Outbox]:
    stmt = select(Outbox).where(Outbox.published_at.is_(None))
    if tenant_id is not None:
        stmt = stmt.where(Outbox.tenant_id == tenant_id)
    if topic is not None:
        stmt = stmt.where(Outbox.topic == topic)

    stmt = (
        stmt.order_by(Outbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(batch_size)
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def process_outbox_batch(
    session: AsyncSession,
    batch_size: int = 50,
    handlers: Optional[Dict[str, Handler]] = None,
    tenant_id: Optional[UUID] = None,
    topic: Optional[str] = None,
) -> int:
    handler_map = handlers or default_handlers()
    async with session.begin():
        rows = await fetch_outbox_batch(
            session,
            batch_size,
            tenant_id=tenant_id,
            topic=topic,
        )
        if not rows:
            return 0

        for row in rows:
            handler = handler_map.get(row.topic)
            if handler is None:
                row.published_at = utcnow()
                continue
            await handler(session, row)
            row.published_at = utcnow()

    return len(rows)
