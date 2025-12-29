from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.db.models.activity import Activity
from libs.db.models.resource import Resource
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AgentMeta:
    source_activity_id: Optional[UUID] = None
    model: Optional[str] = None
    prompt_hash: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args_hash: Optional[str] = None
    tool_result_hash: Optional[str] = None

    def has_agent_data(self) -> bool:
        return bool(self.source_activity_id or self.tool_name or self.prompt_hash)


async def record_agent_activities(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_principal_id: UUID,
    resource: Resource,
    message_id: Optional[UUID],
    meta: AgentMeta,
) -> list[Activity]:
    if not meta.has_agent_data():
        return []

    activities: list[Activity] = []
    invoked = ActivityEnvelope(
        tenant_id=tenant_id,
        actor_principal_id=actor_principal_id,
        resource_id=resource.id,
        resource_type=resource.type,
        action="agent.invoked",
        payload={
            "source_activity_id": str(meta.source_activity_id)
            if meta.source_activity_id
            else None,
            "model": meta.model,
            "prompt_hash": meta.prompt_hash,
        },
    )
    activities.append(await record_activity_with_outbox(session, invoked))

    if message_id is not None:
        responded = ActivityEnvelope(
            tenant_id=tenant_id,
            actor_principal_id=actor_principal_id,
            resource_id=resource.id,
            resource_type=resource.type,
            action="agent.responded",
            payload={"message_id": str(message_id)},
        )
        activities.append(await record_activity_with_outbox(session, responded))

    if meta.tool_name:
        tool_called = ActivityEnvelope(
            tenant_id=tenant_id,
            actor_principal_id=actor_principal_id,
            resource_id=resource.id,
            resource_type=resource.type,
            action="agent.tool_called",
            payload={
                "tool_name": meta.tool_name,
                "args_hash": meta.tool_args_hash,
                "result_hash": meta.tool_result_hash,
            },
        )
        activities.append(await record_activity_with_outbox(session, tool_called))

    return activities
