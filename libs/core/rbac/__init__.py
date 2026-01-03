from __future__ import annotations

from typing import Any, Dict, Tuple, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import Permission
from libs.core.rbac_casbin import authorize_casbin


async def authorize(
    session: AsyncSession,
    tenant_id: UUID,
    actor_principal_id: UUID,
    resource_id: UUID,
    action_perm: Union[str, Permission],
) -> Tuple[bool, Dict[str, Any]]:
    return await authorize_casbin(
        session, tenant_id, actor_principal_id, resource_id, action_perm
    )


__all__ = ["authorize", "Permission"]
