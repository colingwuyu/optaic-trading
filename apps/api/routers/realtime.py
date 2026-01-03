from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from uuid import UUID

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.schemas import (
    RealtimeBootstrapChannel,
    RealtimeBootstrapResource,
    RealtimeBootstrapResponse,
    RealtimeTokenRequest,
    RealtimeTokenResponse,
)
from libs.core.rbac import authorize
from libs.core.rbac.models import ActorContext, Permission
from libs.core.settings import get_settings
from libs.db.models.chat import Channel
from libs.db.models.resource import Resource
from libs.db.models.subscription import Subscription

router = APIRouter(prefix="/realtime", tags=["Realtime"])

TOKEN_TTL_SECONDS = 3600
_CHANNEL_PREFIXES = {"u", "r", "c"}


def _parse_channel(channel: str) -> Tuple[UUID, str, UUID]:
    parts = channel.split(":")
    if len(parts) != 4 or parts[0] != "t":
        raise HTTPException(
            status_code=400, detail=f"Invalid channel format: {channel}"
        )

    channel_type = parts[2]
    if channel_type not in _CHANNEL_PREFIXES:
        raise HTTPException(status_code=400, detail=f"Invalid channel type: {channel}")

    try:
        tenant_id = UUID(parts[1])
        target_id = UUID(parts[3])
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid channel format: {channel}"
        ) from exc

    return tenant_id, channel_type, target_id


def _issue_token(secret: str, payload: Dict[str, str], expires_at: datetime) -> str:
    claims = dict(payload)
    claims["exp"] = expires_at
    claims["iat"] = datetime.now(timezone.utc)
    return jwt.encode(claims, secret, algorithm="HS256")


@router.post(
    "/token",
    response_model=RealtimeTokenResponse,
)
async def issue_realtime_token(
    payload: RealtimeTokenRequest = Body(
        ...,
        examples={
            "default": {
                "summary": "Get realtime tokens",
                "value": {"channels": []},
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> RealtimeTokenResponse:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS)
    connection_token = _issue_token(
        settings.centrifugo_hmac_secret,
        {"sub": str(actor.id)},
        expires_at,
    )

    if not payload.channels:
        return RealtimeTokenResponse(
            connection_token=connection_token,
            subscriptions={},
        )

    denied: List[Dict[str, object]] = []
    allowed_channels: List[str] = []

    for channel in payload.channels:
        tenant_id, channel_type, target_id = _parse_channel(channel)
        if tenant_id != actor.tenant_id:
            denied.append({"channel": channel, "reason": "tenant_mismatch"})
            continue

        if channel_type == "u":
            if target_id != actor.id:
                denied.append({"channel": channel, "reason": "principal_mismatch"})
            else:
                allowed_channels.append(channel)
            continue

        if channel_type == "r":
            decision_allowed, explain = await authorize(
                db,
                actor.tenant_id,
                actor.id,
                target_id,
                Permission.SUBSCRIBE_RESOURCE,
            )
        else:
            decision_allowed, explain = await authorize(
                db,
                actor.tenant_id,
                actor.id,
                target_id,
                Permission.CHANNEL_VIEW_HISTORY,
            )

        if not decision_allowed:
            denied.append(
                {
                    "channel": channel,
                    "reason": "forbidden",
                    "explain": explain,
                }
            )
            continue

        allowed_channels.append(channel)

    if denied:
        raise HTTPException(status_code=403, detail={"denied_channels": denied})

    subscriptions = {
        channel: _issue_token(
            settings.centrifugo_hmac_secret,
            {"sub": str(actor.id), "channel": channel},
            expires_at,
        )
        for channel in allowed_channels
    }
    return RealtimeTokenResponse(
        connection_token=connection_token,
        subscriptions=subscriptions,
    )


@router.get("/bootstrap", response_model=RealtimeBootstrapResponse)
async def realtime_bootstrap(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> RealtimeBootstrapResponse:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS)
    connection_token = _issue_token(
        settings.centrifugo_hmac_secret,
        {"sub": str(actor.id)},
        expires_at,
    )

    tenant_id = actor.tenant_id
    inbox_channel = f"t:{tenant_id}:u:{actor.id}"

    subscription_tokens: Dict[str, str] = {}

    def issue_subscription(channel: str) -> None:
        subscription_tokens[channel] = _issue_token(
            settings.centrifugo_hmac_secret,
            {"sub": str(actor.id), "channel": channel},
            expires_at,
        )

    issue_subscription(inbox_channel)

    chat_channels: List[RealtimeBootstrapChannel] = []
    result = await db.execute(
        select(Channel, Resource)
        .join(Resource, Resource.id == Channel.resource_id)
        .where(
            Channel.tenant_id == tenant_id,
            Resource.tenant_id == tenant_id,
        )
        .order_by(Resource.created_at)
    )
    for channel, resource in result.all():
        allowed, _explain = await authorize(
            db,
            tenant_id,
            actor.id,
            channel.resource_id,
            Permission.CHANNEL_VIEW_HISTORY,
        )
        if not allowed:
            continue
        channel_name = f"t:{tenant_id}:c:{channel.resource_id}"
        chat_channels.append(
            RealtimeBootstrapChannel(
                id=channel.resource_id,
                name=resource.name,
                channel=channel_name,
            )
        )
        issue_subscription(channel_name)

    resource_subscriptions: List[RealtimeBootstrapResource] = []
    seen_resources: set[UUID] = set()
    sub_result = await db.scalars(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id,
            Subscription.principal_id == actor.id,
            Subscription.revoked_at.is_(None),
        )
    )
    for subscription in sub_result.all():
        if subscription.resource_id in seen_resources:
            continue
        perm = (
            Permission.SUBSCRIBE_RESOURCE
            if subscription.scope == "resource"
            else Permission.SUBSCRIBE_DESCENDANTS
        )
        allowed, _explain = await authorize(
            db,
            tenant_id,
            actor.id,
            subscription.resource_id,
            perm,
        )
        if not allowed:
            continue
        seen_resources.add(subscription.resource_id)
        channel_name = f"t:{tenant_id}:r:{subscription.resource_id}"
        resource_subscriptions.append(
            RealtimeBootstrapResource(
                resource_id=subscription.resource_id,
                channel=channel_name,
            )
        )
        issue_subscription(channel_name)

    return RealtimeBootstrapResponse(
        tenant_id=tenant_id,
        principal_id=actor.id,
        inbox_channel=inbox_channel,
        chat_channels=chat_channels,
        resource_subscriptions=resource_subscriptions,
        connection_token=connection_token,
        subscription_tokens=subscription_tokens,
    )
