from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac import authorize as authorize_simple
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.resource import Resource


async def get_resource_or_404(
    db: AsyncSession, tenant_id: UUID, resource_id: UUID
) -> Resource:
    result = await db.scalars(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.tenant_id == tenant_id,
        )
    )
    resource = result.first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


async def authorize_or_403(
    db: AsyncSession, actor: ActorContext, permission: Permission, resource_id: UUID
) -> None:
    allowed, explain = await authorize_simple(
        db,
        actor.tenant_id,
        actor.id,
        resource_id,
        permission,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail=explain)
