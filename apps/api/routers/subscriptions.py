from __future__ import annotations

from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session, utcnow
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import SubscriptionCreate, SubscriptionOut
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.subscription import Subscription

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


def _permission_for_scope(scope: str) -> Permission:
    if scope == "resource":
        return Permission.SUBSCRIBE_RESOURCE
    if scope == "descendants":
        return Permission.SUBSCRIBE_DESCENDANTS
    raise HTTPException(status_code=400, detail="Invalid subscription scope")


@router.post("", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    payload: SubscriptionCreate = Body(
        ...,
        examples={
            "resource": {
                "summary": "Subscribe to resource",
                "value": {
                    "resource_id": "11111111-1111-1111-1111-111111111111",
                    "scope": "resource",
                },
            },
            "descendants": {
                "summary": "Subscribe to descendants",
                "value": {
                    "resource_id": "11111111-1111-1111-1111-111111111111",
                    "scope": "descendants",
                },
            },
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    resource = await get_resource_or_404(db, actor.tenant_id, payload.resource_id)
    permission = _permission_for_scope(payload.scope)
    await authorize_or_403(db, actor, permission, resource.id)

    subscription_id = uuid4()
    resource_id = resource.id
    resource_type = resource.type
    scope = payload.scope

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Subscription:
        subscription = Subscription(
            id=subscription_id,
            tenant_id=actor.tenant_id,
            principal_id=actor.id,
            resource_id=resource_id,
            scope=scope,
        )
        session.add(subscription)
        await session.flush()
        return subscription

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="subscription.created",
        payload={"scope": scope, "resource_id": str(resource_id)},
    )
    subscription, _activity = await tx_activity(db, envelope, domain_fn)
    return SubscriptionOut.model_validate(subscription)


@router.delete("/{subscription_id}", response_model=SubscriptionOut)
async def revoke_subscription(
    subscription_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    result = await db.scalars(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.tenant_id == actor.tenant_id,
        )
    )
    subscription = result.first()
    if not subscription or subscription.principal_id != actor.id:
        raise HTTPException(status_code=404, detail="Subscription not found")

    resource = await get_resource_or_404(db, actor.tenant_id, subscription.resource_id)
    resource_id = resource.id
    resource_type = resource.type

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Subscription:
        target = await session.scalar(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        if not target:
            raise HTTPException(status_code=404, detail="Subscription not found")
        target.revoked_at = utcnow()
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action="subscription.revoked",
        payload={
            "subscription_id": str(subscription_id),
            "resource_id": str(resource_id),
        },
    )
    revoked, _activity = await tx_activity(db, envelope, domain_fn)
    return SubscriptionOut.model_validate(revoked)


@router.get("", response_model=List[SubscriptionOut])
async def list_subscriptions(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> List[SubscriptionOut]:
    result = await db.scalars(
        select(Subscription)
        .where(
            Subscription.tenant_id == actor.tenant_id,
            Subscription.principal_id == actor.id,
            Subscription.revoked_at.is_(None),
        )
        .order_by(Subscription.created_at.desc())
    )
    return [SubscriptionOut.model_validate(sub) for sub in result.all()]
