from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import asyncio

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import Permission, GLOBAL_RESOURCE_TYPE
from libs.core.versioning import create_version, get_current_head, update_ref
from libs.db.models.agent import AgentPolicy
from libs.db.models.chat import Channel, Message
from libs.db.models.identity import Principal, Tenant
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.db.models.resource import Resource


@dataclass(frozen=True)
class DemoIds:
    tenant_id: UUID
    root_resource_id: UUID
    alice_id: UUID
    bob_id: UUID
    agent_id: UUID
    channel_id: UUID


_DEFAULT_ROLE_PERMISSIONS = {
    "owner": [perm.value for perm in Permission],
    "operator": [
        Permission.CHANNEL_VIEW_HISTORY.value,
        Permission.CHANNEL_POST.value,
        Permission.CHANNEL_EDIT_OWN.value,
        Permission.CHANNEL_DELETE_OWN.value,
    ],
    "viewer": [
        Permission.RESOURCE_READ.value,
        Permission.VIEW_ACTIVITY_FEED.value,
    ],
    "auditor": [Permission.VIEW_ACTIVITY_FEED.value],
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _configure_sqlite_pragmas(engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


async def seed_demo(database_url: str) -> DemoIds:
    for attempt in range(1, 6):
        engine = _create_engine(database_url)
        _configure_sqlite_pragmas(engine)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_maker() as session:
                return await _seed(session)
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower() or attempt >= 5:
                raise
            await asyncio.sleep(0.5 * attempt)
        finally:
            await engine.dispose()
    raise RuntimeError("Failed to seed demo data after multiple attempts.")


def _create_engine(database_url: str):
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["timeout"] = 30
    return create_async_engine(
        database_url,
        echo=False,
        poolclass=NullPool,
        connect_args=connect_args or None,
    )


async def _seed(session: AsyncSession) -> DemoIds:
    tenant_id = uuid4()
    root_resource_id = uuid4()
    alice_id = uuid4()
    bob_id = uuid4()
    agent_id = uuid4()
    tenant_name = "OptAIC Demo Workspace"

    async with session.begin():
        tenant = Tenant(id=tenant_id, name=tenant_name)
        session.add(tenant)
        await session.flush()

        session.add_all(
            [
                Principal(
                    id=alice_id,
                    tenant_id=tenant_id,
                    kind="user",
                    status="active",
                    display_name="Alice",
                    email="alice@example.com",
                ),
                Principal(
                    id=bob_id,
                    tenant_id=tenant_id,
                    kind="user",
                    status="active",
                    display_name="Bob",
                    email="bob@example.com",
                ),
                Principal(
                    id=agent_id,
                    tenant_id=tenant_id,
                    kind="agent",
                    status="active",
                    display_name="Agent",
                ),
            ]
        )

        root_resource = Resource(
            id=root_resource_id,
            tenant_id=tenant_id,
            type="TenantRoot",
            parent_id=None,
            owner_principal_id=alice_id,
            name=f"{tenant_name} Root",
            status="active",
            metadata_json={"root": True},
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        session.add(root_resource)
        await session.flush()

        role_rows = []
        for role_name, perms in _DEFAULT_ROLE_PERMISSIONS.items():
            for perm_name in perms:
                role_rows.append(
                    RolePermission(
                        tenant_id=tenant_id,
                        resource_type=GLOBAL_RESOURCE_TYPE,
                        role_name=role_name,
                        perm_name=perm_name,
                    )
                )
        session.add_all(role_rows)

        session.add_all(
            [
                RoleBinding(
                    tenant_id=tenant_id,
                    principal_id=alice_id,
                    scope_resource_id=root_resource_id,
                    role_name="owner",
                    granted_by=alice_id,
                ),
                RoleBinding(
                    tenant_id=tenant_id,
                    principal_id=bob_id,
                    scope_resource_id=root_resource_id,
                    role_name="viewer",
                    granted_by=alice_id,
                ),
            ]
        )

    alice_space = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Space",
        parent_id=root_resource_id,
        name="Alice Personal Space",
        metadata={"owner": "alice"},
        space_kind="personal",
    )
    bob_space = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=bob_id,
        resource_type="Space",
        parent_id=root_resource_id,
        name="Bob Personal Space",
        metadata={"owner": "bob"},
        space_kind="personal",
    )
    team_space = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Space",
        parent_id=root_resource_id,
        name="Team Space",
        metadata={"purpose": "shared"},
        space_kind="team",
    )
    system_space = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Space",
        parent_id=root_resource_id,
        name="System Space",
        metadata={"system": True},
        space_kind="system",
    )

    await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Subspace",
        parent_id=alice_space.id,
        name="Alice Official",
        subspace_kind="official",
    )
    await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=bob_id,
        resource_type="Subspace",
        parent_id=bob_space.id,
        name="Bob Official",
        subspace_kind="official",
    )

    team_official = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Subspace",
        parent_id=team_space.id,
        name="Team Official",
        subspace_kind="official",
    )
    await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Subspace",
        parent_id=team_space.id,
        name="Team Staging",
        subspace_kind="staging",
    )
    await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Subspace",
        parent_id=team_space.id,
        name="Team Labs",
        subspace_kind="custom",
    )

    await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Subspace",
        parent_id=system_space.id,
        name="System Official",
        subspace_kind="official",
    )

    project = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Project",
        parent_id=team_official.id,
        name="Fusion Initiative",
        metadata={"stage": "official", "summary": "Demo project for OptAIC"},
    )
    dataset = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Dataset",
        parent_id=project.id,
        name="Core Signals Dataset",
        metadata={"status": "active", "owner": "alice"},
    )
    experiment = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Experiment",
        parent_id=project.id,
        name="Pricing Experiment",
        metadata={"status": "draft"},
    )
    extension = await _create_resource_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        resource_type="Extension",
        parent_id=project.id,
        name="Analytics Extension",
        metadata={"framework": "python"},
    )

    async with session.begin():
        await _update_version(
            session,
            project.id,
            {
                "refs": {
                    "dataset": str(dataset.id),
                    "experiment": str(experiment.id),
                    "extension": str(extension.id),
                }
            },
            alice_id,
        )
        await _update_version(
            session,
            dataset.id,
            {
                "pipeline_refs": ["etl:v1", "metrics:v2"],
                "store_refs": ["s3://optaic-demo/core-signals"],
                "accessor_refs": ["pandas", "duckdb"],
                "config": {"schema_version": 1, "owner": "alice"},
            },
            alice_id,
        )
        await _update_version(
            session,
            experiment.id,
            {
                "tabs": [
                    {
                        "id": "overview",
                        "title": "Overview",
                        "blocks": [
                            {
                                "type": "markdown",
                                "content": "Initial pricing uplift experiment.",
                            }
                        ],
                    },
                    {
                        "id": "metrics",
                        "title": "Metrics",
                        "blocks": [
                            {"type": "chart", "metric": "conversion_rate"},
                            {"type": "table", "metric": "cohort_retention"},
                        ],
                    },
                ],
                "expressions": [
                    "uplift = (test_conversion - control_conversion)",
                    "roi = (net_revenue - cost) / cost",
                ],
            },
            alice_id,
        )
        await _update_version(
            session,
            extension.id,
            {
                "files": [
                    {
                        "path": "extensions/analytics.py",
                        "summary": "Demo analytics extension entrypoint.",
                    },
                    {"path": "extensions/models.py", "summary": "Model helpers."},
                ],
                "tests": [
                    {
                        "name": "test_metrics_smoke",
                        "status": "passing",
                        "runtime_ms": 128,
                    },
                    {
                        "name": "test_pipeline_contract",
                        "status": "passing",
                        "runtime_ms": 212,
                    },
                ],
            },
            alice_id,
        )

    channel = await _create_channel_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        parent_id=project.id,
        channel_kind="group",
        name="Team Chat",
        topic="Launch planning",
        settings={"agent_enabled": True},
    )

    async with session.begin():
        session.add_all(
            [
                RoleBinding(
                    tenant_id=tenant_id,
                    principal_id=bob_id,
                    scope_resource_id=channel.resource_id,
                    role_name="operator",
                    granted_by=alice_id,
                ),
                RoleBinding(
                    tenant_id=tenant_id,
                    principal_id=agent_id,
                    scope_resource_id=channel.resource_id,
                    role_name="operator",
                    granted_by=alice_id,
                ),
                AgentPolicy(
                    tenant_id=tenant_id,
                    agent_principal_id=agent_id,
                    policy={
                        "trigger_rules": {
                            "mentions": True,
                            "channels": [str(channel.resource_id)],
                        }
                    },
                ),
            ]
        )

    await _post_message_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=alice_id,
        channel_id=channel.resource_id,
        body="Welcome team! @agent can you summarize the goal for today?",
    )
    await _post_message_with_activity(
        session,
        tenant_id=tenant_id,
        actor_id=bob_id,
        channel_id=channel.resource_id,
        body="Hi all, ready to review the rollout plan.",
    )

    return DemoIds(
        tenant_id=tenant_id,
        root_resource_id=root_resource_id,
        alice_id=alice_id,
        bob_id=bob_id,
        agent_id=agent_id,
        channel_id=channel.resource_id,
    )


async def _create_resource_with_activity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    resource_type: str,
    parent_id: UUID,
    name: str,
    metadata: Optional[dict] = None,
    space_kind: Optional[str] = None,
    subspace_kind: Optional[str] = None,
) -> Resource:
    resource_id = uuid4()

    async def domain_fn(inner: AsyncSession) -> Resource:
        resource = Resource(
            id=resource_id,
            tenant_id=tenant_id,
            type=resource_type,
            parent_id=parent_id,
            owner_principal_id=actor_id,
            name=name,
            status="active",
            metadata_json=metadata or {},
            space_kind=space_kind,
            subspace_kind=subspace_kind,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        inner.add(resource)
        await inner.flush()
        return resource

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="resource.created",
        payload={"parent_id": str(parent_id), "name": name},
    )
    resource, _activity = await tx_activity(session, envelope, domain_fn)
    if resource is None:
        raise RuntimeError("Resource creation returned no resource.")
    return resource


async def _create_channel_with_activity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    parent_id: UUID,
    channel_kind: str,
    name: str,
    topic: Optional[str] = None,
    settings: Optional[dict] = None,
) -> Channel:
    channel_id = uuid4()

    async def domain_fn(inner: AsyncSession) -> Channel:
        resource = Resource(
            id=channel_id,
            tenant_id=tenant_id,
            type="Channel",
            parent_id=parent_id,
            owner_principal_id=actor_id,
            name=name,
            status="active",
            metadata_json={"channel_kind": channel_kind},
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        inner.add(resource)
        await inner.flush()
        channel = Channel(
            resource_id=channel_id,
            tenant_id=tenant_id,
            channel_kind=channel_kind,
            topic=topic,
            settings=settings or {},
        )
        inner.add(channel)
        await inner.flush()
        return channel

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=channel_id,
        resource_type="Channel",
        action="channel.created",
        payload={
            "channel_id": str(channel_id),
            "parent_id": str(parent_id),
            "channel_kind": channel_kind,
        },
    )
    channel, _activity = await tx_activity(session, envelope, domain_fn)
    if channel is None:
        raise RuntimeError("Channel creation returned no channel.")
    return channel


async def _post_message_with_activity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    channel_id: UUID,
    body: str,
) -> Message:
    message_id = uuid4()

    async def domain_fn(inner: AsyncSession) -> Message:
        message = Message(
            id=message_id,
            tenant_id=tenant_id,
            channel_id=channel_id,
            sender_principal_id=actor_id,
            body=body,
            body_json=None,
            status="active",
        )
        inner.add(message)
        await inner.flush()
        return message

    envelope = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_id,
        resource_id=channel_id,
        resource_type="Channel",
        action="message.posted",
        payload={"message_id": str(message_id), "channel_id": str(channel_id)},
    )
    message, _activity = await tx_activity(session, envelope, domain_fn)
    if message is None:
        raise RuntimeError("Message creation returned no message.")
    return message


async def _update_version(
    session: AsyncSession,
    resource_id: UUID,
    content: dict,
    actor_id: UUID,
) -> None:
    head = await get_current_head(session, resource_id, ref_name="main")
    parents = [head.id] if head else []
    version = await create_version(session, resource_id, parents, content, actor_id)
    await update_ref(session, resource_id, "main", version.id, actor_id)
