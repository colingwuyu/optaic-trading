from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.settings import get_settings
from libs.db.models.activity import Activity
from libs.db.models.agent import AgentCursor, AgentPolicy
from libs.db.models.chat import Channel, Message
from libs.db.models.identity import Principal
from libs.db.session import AsyncSessionLocal
from libs.sdk_py.client import AsyncPlatformClient


_MENTION_TOKEN = "@agent"


@dataclass(frozen=True)
class AgentRunResult:
    processed: int
    responded: int


class StubLLM:
    def __init__(self, model: str) -> None:
        self.model = model

    async def respond(self, prompt: str) -> str:
        snippet = prompt.strip().replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "..."
        return f"Agent ({self.model}) received: {snippet}"


class AgentRunner:
    def __init__(
        self,
        *,
        api_base_url: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: int = 50,
        client_factory: Optional[
            Callable[[UUID, UUID], AsyncPlatformClient]
        ] = None,
    ) -> None:
        settings = get_settings()
        self.api_base_url = api_base_url or settings.agent_api_base_url
        self.model = model or settings.agent_model
        self.batch_size = batch_size or settings.agent_batch_size
        self.logger = structlog.get_logger("agent.runner")
        self.llm = StubLLM(self.model)
        self._client_factory = client_factory

    async def run_once(self) -> AgentRunResult:
        processed = 0
        responded = 0
        async with AsyncSessionLocal() as session:
            policies = await self._load_policies(session)

        for policy in policies:
            result = await self._process_policy(policy)
            processed += result.processed
            responded += result.responded

        return AgentRunResult(processed=processed, responded=responded)

    async def _process_policy(self, policy: AgentPolicy) -> AgentRunResult:
        tenant_id = policy.tenant_id
        agent_id = policy.agent_principal_id

        async with AsyncSessionLocal() as session:
            principal = await session.scalar(
                select(Principal).where(
                    Principal.id == agent_id,
                    Principal.tenant_id == tenant_id,
                )
            )
            if not principal or principal.kind != "agent":
                self.logger.warning(
                    "agent.principal_invalid",
                    tenant_id=str(tenant_id),
                    agent_principal_id=str(agent_id),
                )
                return AgentRunResult(processed=0, responded=0)

            cursor = await self._get_or_create_cursor(session, tenant_id, agent_id)
            activities = await self._fetch_activities(
                session,
                tenant_id,
                cursor.last_activity_created_at,
                cursor.last_activity_id,
                self.batch_size,
            )

        processed = 0
        responded = 0
        client_factory = self._client_factory or (
            lambda tenant, agent: AsyncPlatformClient(
                self.api_base_url,
                principal_id=agent,
                tenant_id=tenant,
            )
        )
        async with client_factory(tenant_id, agent_id) as client:
            for activity in activities:
                processed += 1
                try:
                    did_respond = await self._handle_activity(
                        client, tenant_id, agent_id, policy.policy or {}, activity
                    )
                    if did_respond:
                        responded += 1
                except Exception:
                    self.logger.exception(
                        "agent.activity_failed",
                        tenant_id=str(tenant_id),
                        agent_principal_id=str(agent_id),
                        activity_id=str(activity.id),
                    )
                finally:
                    await self._update_cursor(tenant_id, agent_id, activity)

        return AgentRunResult(processed=processed, responded=responded)

    async def _handle_activity(
        self,
        client: AsyncPlatformClient,
        tenant_id: UUID,
        agent_id: UUID,
        policy: Dict[str, Any],
        activity: Activity,
    ) -> bool:
        if activity.actor_principal_id == agent_id:
            return False

        trigger_rules = policy.get("trigger_rules", {})
        allowed_actions = trigger_rules.get("actions")
        if allowed_actions and activity.action not in allowed_actions:
            return False

        allowed_resource_types = policy.get("allowed_resource_types")
        if allowed_resource_types and activity.resource_type not in allowed_resource_types:
            return False

        if activity.action != "message.posted":
            return False

        payload = activity.payload or {}
        message_id = payload.get("message_id")
        channel_id = payload.get("channel_id")
        if not message_id or not channel_id:
            return False

        async with AsyncSessionLocal() as session:
            message = await session.scalar(
                select(Message).where(
                    Message.id == UUID(str(message_id)),
                    Message.tenant_id == tenant_id,
                )
            )
            if not message or not message.body:
                return False
            channel = await session.scalar(
                select(Channel).where(
                    Channel.resource_id == UUID(str(channel_id)),
                    Channel.tenant_id == tenant_id,
                )
            )

        mention_trigger = trigger_rules.get("mentions", True)
        has_mention = mention_trigger and _MENTION_TOKEN in message.body.lower()
        channel_enabled = bool(channel and channel.settings.get("agent_enabled"))
        allowed_channels = trigger_rules.get("channels")
        if allowed_channels and str(channel_id) not in {str(c) for c in allowed_channels}:
            return False
        if not (has_mention or channel_enabled):
            return False

        reply = await self.llm.respond(message.body)
        prompt_hash = hashlib.sha256(message.body.encode("utf-8")).hexdigest()
        headers = {
            "X-Agent-Source-Activity-Id": str(activity.id),
            "X-Agent-Model": self.model,
            "X-Agent-Prompt-Hash": prompt_hash,
        }
        tool_headers = self._maybe_tool_headers(policy, activity)
        if tool_headers:
            headers.update(tool_headers)
        await client.chat.send_message(
            channel_id,
            reply,
            principal_id=agent_id,
            tenant_id=tenant_id,
            headers=headers,
        )
        return True

    def _maybe_tool_headers(
        self, policy: Dict[str, Any], activity: Activity
    ) -> Dict[str, str]:
        allowed_tools = policy.get("allowed_tools") or []
        if not allowed_tools:
            return {}
        tool_name = str(allowed_tools[0])
        args_payload = f"{activity.action}:{activity.id}"
        args_hash = hashlib.sha256(args_payload.encode("utf-8")).hexdigest()
        result_hash = hashlib.sha256(b"ok").hexdigest()
        return {
            "X-Agent-Tool-Name": tool_name,
            "X-Agent-Tool-Args-Hash": args_hash,
            "X-Agent-Tool-Result-Hash": result_hash,
        }

    async def _load_policies(self, session: AsyncSession) -> List[AgentPolicy]:
        result = await session.scalars(select(AgentPolicy))
        return list(result.all())

    async def _get_or_create_cursor(
        self, session: AsyncSession, tenant_id: UUID, agent_id: UUID
    ) -> AgentCursor:
        cursor = await session.scalar(
            select(AgentCursor).where(
                AgentCursor.tenant_id == tenant_id,
                AgentCursor.agent_principal_id == agent_id,
            )
        )
        if cursor:
            return cursor
        cursor = AgentCursor(
            tenant_id=tenant_id,
            agent_principal_id=agent_id,
            last_activity_created_at=None,
            last_activity_id=None,
        )
        session.add(cursor)
        await session.commit()
        return cursor

    async def _fetch_activities(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        last_created_at: Optional[datetime],
        last_activity_id: Optional[UUID],
        limit: int,
    ) -> List[Activity]:
        stmt = select(Activity).where(Activity.tenant_id == tenant_id)
        if last_created_at is not None and last_activity_id is not None:
            stmt = stmt.where(
                or_(
                    Activity.created_at > last_created_at,
                    and_(
                        Activity.created_at == last_created_at,
                        Activity.id > last_activity_id,
                    ),
                )
            )
        stmt = stmt.order_by(Activity.created_at.asc(), Activity.id.asc()).limit(limit)
        result = await session.scalars(stmt)
        return list(result.all())

    async def _update_cursor(
        self,
        tenant_id: UUID,
        agent_id: UUID,
        activity: Activity,
    ) -> None:
        async with AsyncSessionLocal() as session:
            cursor = await session.scalar(
                select(AgentCursor).where(
                    AgentCursor.tenant_id == tenant_id,
                    AgentCursor.agent_principal_id == agent_id,
                )
            )
            if not cursor:
                cursor = AgentCursor(
                    tenant_id=tenant_id,
                    agent_principal_id=agent_id,
                )
                session.add(cursor)
            cursor.last_activity_created_at = activity.created_at
            cursor.last_activity_id = activity.id
            await session.commit()
