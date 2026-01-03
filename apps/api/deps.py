from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator, Annotated, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import ActorContext
from apps.api.agent_utils import AgentMeta
from libs.db.models.identity import Principal
from libs.db.session import AsyncSessionLocal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_principal_id(
    x_principal_id: Annotated[str, Header(alias="X-Principal-Id")],
) -> UUID:
    try:
        return UUID(x_principal_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid X-Principal-Id header"
        ) from exc


async def get_tenant_id(
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-Id")],
) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid X-Tenant-Id header"
        ) from exc


async def get_actor(
    principal_id: UUID = Depends(get_principal_id),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ActorContext:
    result = await db.scalars(select(Principal).where(Principal.id == principal_id))
    principal = result.first()
    if not principal:
        raise HTTPException(status_code=401, detail="Unknown principal")
    if principal.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403, detail="Principal does not belong to tenant"
        )
    return ActorContext(id=principal.id, tenant_id=tenant_id, kind=principal.kind)


async def get_agent_meta(
    x_agent_source_activity_id: Annotated[
        Optional[str], Header(alias="X-Agent-Source-Activity-Id")
    ] = None,
    x_agent_model: Annotated[Optional[str], Header(alias="X-Agent-Model")] = None,
    x_agent_prompt_hash: Annotated[
        Optional[str], Header(alias="X-Agent-Prompt-Hash")
    ] = None,
    x_agent_tool_name: Annotated[
        Optional[str], Header(alias="X-Agent-Tool-Name")
    ] = None,
    x_agent_tool_args_hash: Annotated[
        Optional[str], Header(alias="X-Agent-Tool-Args-Hash")
    ] = None,
    x_agent_tool_result_hash: Annotated[
        Optional[str], Header(alias="X-Agent-Tool-Result-Hash")
    ] = None,
) -> AgentMeta:
    source_id = None
    if x_agent_source_activity_id:
        try:
            source_id = UUID(x_agent_source_activity_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid X-Agent-Source-Activity-Id header"
            ) from exc
    return AgentMeta(
        source_activity_id=source_id,
        model=x_agent_model,
        prompt_hash=x_agent_prompt_hash,
        tool_name=x_agent_tool_name,
        tool_args_hash=x_agent_tool_args_hash,
        tool_result_hash=x_agent_tool_result_hash,
    )


async def reset_session(db: AsyncSession) -> None:
    if db.in_transaction():
        await db.rollback()


def get_guardrails_engine() -> "GuardrailsEngine":  # noqa: F821
    from optaic.guardrails.runtime.engine import GuardrailsEngine

    return GuardrailsEngine()
