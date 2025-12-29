from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.models.activity import Activity
from libs.db.models.identity import Principal
from libs.db.models.resource import Resource


class ActivityActor(BaseModel):
    principal_id: UUID
    kind: str
    display_name: Optional[str] = None


class ActivityResource(BaseModel):
    resource_id: UUID
    resource_type: str
    parent_id: Optional[UUID] = None


class ActivityUiHints(BaseModel):
    category: Optional[str] = None
    severity: Optional[str] = None
    icon: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None


class ActivityTargets(BaseModel):
    user_inbox: Optional[list[UUID]] = None
    chat_channels: Optional[list[UUID]] = None
    resource_channels: Optional[list[UUID]] = None


class ActivityEventV1(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: str = Field(default="1")
    event_id: UUID
    tenant_id: UUID
    created_at: datetime
    correlation_id: UUID
    actor: ActivityActor
    resource: ActivityResource
    action: str
    target_principal_id: Optional[UUID] = None
    visibility: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    authz_decision: Optional[str] = None
    ui_hints: Optional[ActivityUiHints] = None
    targets: Optional[ActivityTargets] = None


async def _get_principal(
    session: AsyncSession,
    principal_id: UUID,
    cache: Optional[Dict[UUID, Principal]],
) -> Optional[Principal]:
    if cache is not None and principal_id in cache:
        return cache[principal_id]
    result = await session.scalars(
        select(Principal).where(Principal.id == principal_id)
    )
    principal = result.first()
    if cache is not None and principal is not None:
        cache[principal_id] = principal
    return principal


async def _get_resource(
    session: AsyncSession,
    resource_id: UUID,
    cache: Optional[Dict[UUID, Resource]],
) -> Optional[Resource]:
    if cache is not None and resource_id in cache:
        return cache[resource_id]
    result = await session.scalars(select(Resource).where(Resource.id == resource_id))
    resource = result.first()
    if cache is not None and resource is not None:
        cache[resource_id] = resource
    return resource


def _coerce_uuid(value: object) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _targets_from_activity(activity: Activity) -> Optional[ActivityTargets]:
    user_inbox: list[UUID] = []
    chat_channels: list[UUID] = []
    resource_channels: list[UUID] = []

    if activity.target_principal_id is not None:
        user_inbox.append(activity.target_principal_id)

    if activity.resource_id is not None:
        resource_channels.append(activity.resource_id)

    action = activity.action or ""
    if action.startswith(("message.", "receipt.")):
        channel_id: Optional[UUID] = None
        payload = activity.payload or {}
        if isinstance(payload, dict):
            channel_id = _coerce_uuid(payload.get("channel_id"))
        if channel_id is None and activity.resource_type == "Channel":
            channel_id = activity.resource_id
        if channel_id is not None:
            chat_channels.append(channel_id)

    if action.startswith("invite.") and not user_inbox:
        payload = activity.payload or {}
        if isinstance(payload, dict):
            candidate = (
                payload.get("invitee_principal_id")
                or payload.get("target_principal_id")
                or payload.get("principal_id")
            )
            invitee = _coerce_uuid(candidate)
            if invitee is not None:
                user_inbox.append(invitee)

    if not user_inbox and not chat_channels and not resource_channels:
        return None

    return ActivityTargets(
        user_inbox=user_inbox or None,
        chat_channels=chat_channels or None,
        resource_channels=resource_channels or None,
    )


async def build_activity_event(
    session: AsyncSession,
    activity: Activity,
    *,
    principal_cache: Optional[Dict[UUID, Principal]] = None,
    resource_cache: Optional[Dict[UUID, Resource]] = None,
    authz_decision: Optional[str] = None,
    ui_hints: Optional[ActivityUiHints] = None,
) -> ActivityEventV1:
    principal = await _get_principal(
        session, activity.actor_principal_id, principal_cache
    )
    resource = await _get_resource(session, activity.resource_id, resource_cache)
    actor = ActivityActor(
        principal_id=activity.actor_principal_id,
        kind=principal.kind if principal else "unknown",
        display_name=principal.display_name if principal else None,
    )
    resource_payload = ActivityResource(
        resource_id=activity.resource_id,
        resource_type=activity.resource_type,
        parent_id=resource.parent_id if resource else None,
    )
    return ActivityEventV1(
        event_id=activity.id,
        tenant_id=activity.tenant_id,
        created_at=activity.created_at,
        correlation_id=activity.correlation_id,
        actor=actor,
        resource=resource_payload,
        action=activity.action,
        target_principal_id=activity.target_principal_id,
        visibility=activity.visibility,
        payload=activity.payload or {},
        authz_decision=authz_decision,
        ui_hints=ui_hints,
        targets=_targets_from_activity(activity),
    )
