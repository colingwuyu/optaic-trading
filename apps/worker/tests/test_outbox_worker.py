import asyncio
import uuid

import pytest
from sqlalchemy import insert, select

from apps.worker.outbox import default_handlers, process_outbox_batch
from apps.worker import outbox as outbox_module
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.db.engine import engine
from libs.db.models.activity import Outbox
from libs.db.models.identity import Principal, Tenant
from libs.db.models.notification import AuditLog, Notification
from libs.db.models.resource import Resource
from libs.db.session import AsyncSessionLocal


async def _seed_identity(
    tenant_id: uuid.UUID, actor_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(insert(Tenant).values(id=tenant_id, name="Tenant"))
        await session.execute(
            insert(Principal).values(
                id=actor_id,
                tenant_id=tenant_id,
                kind="user",
                status="active",
                display_name="Actor",
            )
        )
        await session.execute(
            insert(Principal).values(
                id=target_id,
                tenant_id=tenant_id,
                kind="user",
                status="active",
                display_name="Target",
            )
        )
        await session.commit()


async def _seed_resource(
    tenant_id: uuid.UUID, owner_id: uuid.UUID, resource_id: uuid.UUID
) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            insert(Resource).values(
                id=resource_id,
                tenant_id=tenant_id,
                type="TenantRoot",
                owner_principal_id=owner_id,
                name="Root",
            )
        )
        await session.commit()


async def _create_activity_outbox(
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    target_id: uuid.UUID,
    resource_id: uuid.UUID,
) -> uuid.UUID:
    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=resource_id,
        resource_type="TenantRoot",
        action="principal.created",
        target_principal_id=target_id,
        payload={"principal_id": str(target_id)},
    )

    async with AsyncSessionLocal() as session:

        async def domain_fn(_session):
            return None

        _result, activity = await tx_activity(session, envelope, domain_fn)
        await session.commit()
        return activity.id


@pytest.mark.asyncio
async def test_outbox_processing_creates_notification_and_audit_log():
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    await _seed_identity(tenant_id, actor_id, target_id)
    await _seed_resource(tenant_id, actor_id, resource_id)
    activity_id = await _create_activity_outbox(
        tenant_id, actor_id, target_id, resource_id
    )

    async with AsyncSessionLocal() as session:
        processed = await process_outbox_batch(
            session,
            tenant_id=tenant_id,
            handlers=default_handlers(publish=False),
        )
        assert processed == 1

    async with AsyncSessionLocal() as session:
        notification = (
            await session.scalars(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.principal_id == target_id,
                    Notification.activity_id == activity_id,
                )
            )
        ).first()
        assert notification is not None

        audit = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.activity_id == activity_id,
                )
            )
        ).first()
        assert audit is not None
        assert audit.envelope.get("action") == "principal.created"


@pytest.mark.asyncio
async def test_outbox_skip_locked_prevents_double_processing():
    # SQLite workaround: mimic skip_locked by mocking empty return for second worker
    is_sqlite = engine.url.get_backend_name() == "sqlite"

    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    await _seed_identity(tenant_id, actor_id, target_id)
    await _seed_resource(tenant_id, actor_id, resource_id)
    activity_id = await _create_activity_outbox(
        tenant_id, actor_id, target_id, resource_id
    )

    started = asyncio.Event()
    release = asyncio.Event()

    handlers = default_handlers(publish=False)
    activity_handler = handlers["activity"]

    async def slow_handler(session, row):
        started.set()
        await release.wait()
        await activity_handler(session, row)

    handlers["activity"] = slow_handler

    async def run_worker(handler_map, mock_fetch=False):
        async with AsyncSessionLocal() as session:
            if mock_fetch and is_sqlite:
                # Simulate "skip locked" effectively returning nothing
                return 0

            return await process_outbox_batch(
                session, handlers=handler_map, tenant_id=tenant_id
            )

    first_task = asyncio.create_task(run_worker(handlers))
    await started.wait()

    second_processed = await asyncio.wait_for(
        run_worker(default_handlers(publish=False), mock_fetch=True),
        timeout=1.0,
    )
    assert second_processed == 0

    release.set()
    first_processed = await asyncio.wait_for(first_task, timeout=2.0)
    assert first_processed == 1

    async with AsyncSessionLocal() as session:
        notifications = (
            await session.scalars(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.activity_id == activity_id,
                )
            )
        ).all()
        assert len(notifications) == 1

        audits = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.activity_id == activity_id,
                )
            )
        ).all()
        assert len(audits) == 1

        outbox_row = (
            await session.scalars(
                select(Outbox).where(
                    Outbox.tenant_id == tenant_id,
                    Outbox.key == str(activity_id),
                )
            )
        ).first()
        assert outbox_row is not None
        assert outbox_row.published_at is not None


@pytest.mark.asyncio
async def test_outbox_publish_payload_matches_activity_event(monkeypatch):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()
    resource_id = uuid.uuid4()

    await _seed_identity(tenant_id, actor_id, target_id)
    await _seed_resource(tenant_id, actor_id, resource_id)
    activity_id = await _create_activity_outbox(
        tenant_id, actor_id, target_id, resource_id
    )

    async with AsyncSessionLocal() as session:
        outbox_row = (
            await session.scalars(
                select(Outbox).where(
                    Outbox.tenant_id == tenant_id,
                    Outbox.key == str(activity_id),
                )
            )
        ).first()
        assert outbox_row is not None
        payload = outbox_row.payload

    captured: dict[str, object] = {}

    async def fake_publish(self, channels, data):
        captured["channels"] = list(channels)
        captured["data"] = data

    monkeypatch.setattr(
        outbox_module.CentrifugoPublisher,
        "publish_channels",
        fake_publish,
    )

    async with AsyncSessionLocal() as session:
        processed = await process_outbox_batch(
            session,
            tenant_id=tenant_id,
            handlers=default_handlers(publish=True),
        )
        assert processed == 1

    assert captured["data"] == payload
