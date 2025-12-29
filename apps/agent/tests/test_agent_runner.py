import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from apps.agent.runner import AgentRunner
from apps.api.main import app
from libs.db.models.activity import Activity
from libs.db.models.agent import AgentPolicy
from libs.db.session import AsyncSessionLocal
from libs.sdk_py.client import AsyncPlatformClient


@pytest.mark.asyncio
async def test_agent_responds_to_mentions_with_audit_activity():
    owner_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tenant_response = await client.post(
            "/tenants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"name": "Agent Tenant"},
        )
        assert tenant_response.status_code == 201
        root_resource_id = tenant_response.json()["root_resource_id"]

        agent_response = await client.post(
            "/principals",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "id": str(agent_id),
                "display_name": "Agent",
                "kind": "agent",
            },
        )
        assert agent_response.status_code == 201

        channel_response = await client.post(
            "/chat/channels",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "parent_id": root_resource_id,
                "channel_kind": "group",
                "name": "Agent Channel",
                "settings": {"agent_enabled": True},
            },
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["resource_id"]

        grant_response = await client.post(
            "/rbac/grants",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={
                "principal_id": str(agent_id),
                "role_name": "operator",
                "scope_resource_id": channel_id,
            },
        )
        assert grant_response.status_code == 201

        message_response = await client.post(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
            json={"body": "Hello @agent, are you there?"},
        )
        assert message_response.status_code == 201

    async with AsyncSessionLocal() as session:
        await session.execute(
            insert(AgentPolicy).values(
                tenant_id=tenant_id,
                agent_principal_id=agent_id,
                policy={"trigger_rules": {"mentions": True}},
            )
        )
        await session.commit()

    def client_factory(tenant: uuid.UUID, agent: uuid.UUID) -> AsyncPlatformClient:
        http_client = AsyncClient(transport=transport, base_url="http://test")
        return AsyncPlatformClient(
            "http://test",
            principal_id=agent,
            tenant_id=tenant,
            client=http_client,
        )

    runner = AgentRunner(client_factory=client_factory)
    result = await runner.run_once()
    assert result.responded >= 1

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        history = await client.get(
            f"/chat/channels/{channel_id}/messages",
            headers={"X-Principal-Id": str(owner_id), "X-Tenant-Id": str(tenant_id)},
        )
        assert history.status_code == 200
        items = history.json()["items"]
        assert any(item["sender_principal_id"] == str(agent_id) for item in items)

    async with AsyncSessionLocal() as session:
        activities = (
            await session.scalars(
                select(Activity).where(
                    Activity.tenant_id == tenant_id,
                    Activity.resource_id == uuid.UUID(channel_id),
                    Activity.action.in_(["agent.invoked", "agent.responded"]),
                )
            )
        ).all()
        assert {"agent.invoked", "agent.responded"} <= {
            activity.action for activity in activities
        }
