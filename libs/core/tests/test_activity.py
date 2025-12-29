import uuid

import pytest
from sqlalchemy import insert, select

from libs.core.activity import ActivityEnvelope, tx_activity
from libs.db.models.activity import Activity, Outbox
from libs.db.models.identity import Principal, Tenant
from libs.db.models.resource import Resource
from libs.db.session import AsyncSessionLocal


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def _seed_identity(session, tenant_id, principal_id):
    await session.execute(insert(Tenant).values(id=tenant_id, name="Tenant"))
    await session.execute(
        insert(Principal).values(
            id=principal_id,
            tenant_id=tenant_id,
            kind="user",
            status="active",
            display_name="Actor",
        )
    )


@pytest.mark.asyncio
async def test_tx_activity_success_writes_activity_and_outbox(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    child_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, actor_id)
    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Root",
        )
    )

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=resource_id,
        resource_type="Space",
        action="resource.created",
        payload={"name": "Root"},
    )

    async def domain_fn(session):
        await session.execute(
            insert(Resource).values(
                id=child_id,
                tenant_id=tenant_id,
                type="Project",
                parent_id=resource_id,
                owner_principal_id=actor_id,
                name="Child",
            )
        )
        return child_id

    result, activity = await tx_activity(db_session, envelope, domain_fn)

    assert result == child_id
    assert activity.correlation_id == envelope.correlation_id

    activity_row = (
        await db_session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.correlation_id == envelope.correlation_id,
                Activity.action == envelope.action,
                Activity.resource_id == envelope.resource_id,
            )
        )
    ).first()
    assert activity_row is not None

    outbox_row = (
        await db_session.scalars(
            select(Outbox).where(
                Outbox.tenant_id == tenant_id,
                Outbox.topic == "activity",
                Outbox.key == str(activity_row.id),
            )
        )
    ).first()
    assert outbox_row is not None
    payload = outbox_row.payload
    assert payload.get("version") == "1"
    assert payload.get("event_id") == str(activity_row.id)
    assert payload.get("actor", {}).get("principal_id") == str(actor_id)
    assert payload.get("resource", {}).get("resource_id") == str(resource_id)
    targets = payload.get("targets") or {}
    assert str(resource_id) in (targets.get("resource_channels") or [])


@pytest.mark.asyncio
async def test_tx_activity_rolls_back_on_failure(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    attempted_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, actor_id)
    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Root",
        )
    )

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=resource_id,
        resource_type="Space",
        action="resource.updated",
        payload={"name": "Root"},
    )

    async def failing_fn(session):
        await session.execute(
            insert(Resource).values(
                id=attempted_id,
                tenant_id=tenant_id,
                type="Project",
                parent_id=resource_id,
                owner_principal_id=actor_id,
                name="Child",
            )
        )
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await tx_activity(db_session, envelope, failing_fn)

    activity_row = (
        await db_session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.correlation_id == envelope.correlation_id,
                Activity.action == envelope.action,
                Activity.resource_id == envelope.resource_id,
            )
        )
    ).first()
    assert activity_row is None

    outbox_row = (
        await db_session.scalars(
            select(Outbox).where(Outbox.tenant_id == tenant_id)
        )
    ).first()
    assert outbox_row is None

    resource_row = (
        await db_session.scalars(select(Resource).where(Resource.id == attempted_id))
    ).first()
    assert resource_row is None


@pytest.mark.asyncio
async def test_tx_activity_idempotent_by_correlation_action_resource(db_session):
    tenant_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    child_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, actor_id)
    await db_session.execute(
        insert(Resource).values(
            id=resource_id,
            tenant_id=tenant_id,
            type="Space",
            owner_principal_id=actor_id,
            name="Root",
        )
    )

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=resource_id,
        resource_type="Space",
        action="resource.created",
        payload={"name": "Root"},
        correlation_id=correlation_id,
    )

    calls = {"count": 0}

    async def domain_fn(session):
        calls["count"] += 1
        await session.execute(
            insert(Resource).values(
                id=child_id,
                tenant_id=tenant_id,
                type="Project",
                parent_id=resource_id,
                owner_principal_id=actor_id,
                name="Child",
            )
        )
        return child_id

    first_result, first_activity = await tx_activity(db_session, envelope, domain_fn)
    second_result, second_activity = await tx_activity(db_session, envelope, domain_fn)

    assert first_result == child_id
    assert second_result is None
    assert second_activity.id == first_activity.id
    assert calls["count"] == 1

    activity_rows = (
        await db_session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.correlation_id == correlation_id,
                Activity.action == envelope.action,
                Activity.resource_id == envelope.resource_id,
            )
        )
    ).all()
    assert len(activity_rows) == 1

    outbox_rows = (
        await db_session.scalars(
            select(Outbox).where(
                Outbox.tenant_id == tenant_id,
                Outbox.topic == "activity",
                Outbox.key == str(first_activity.id),
            )
        )
    ).all()
    assert len(outbox_rows) == 1
