from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID

import casbin
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import (
    ActorContext,
    DecisionExplanation,
    Permission,
    GLOBAL_RESOURCE_TYPE,
)
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.db.models.resource import Resource

from .adapter import CasbinAdapter

_MODEL_PATH = Path(__file__).with_name("model.conf")


def _resource_obj(resource_id: UUID) -> str:
    return f"res:{resource_id}"


def _permission_value(permission: Union[Permission, str]) -> str:
    if isinstance(permission, Permission):
        return permission.value
    return str(permission)


async def _get_resource(
    session: AsyncSession,
    resource_id: UUID,
    cache: Dict[UUID, Resource],
) -> Optional[Resource]:
    if resource_id in cache:
        return cache[resource_id]

    result = await session.scalars(select(Resource).where(Resource.id == resource_id))
    resource = result.first()
    if resource:
        cache[resource_id] = resource
    return resource


def _deny_decision(
    actor: ActorContext,
    permission: str,
    resource_id: UUID,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    explanation = DecisionExplanation(
        message=message,
        details=details or {},
    )
    return False, explanation.model_dump(mode="json")


async def authorize_casbin(
    session: AsyncSession,
    tenant_id: UUID,
    actor_principal_id: UUID,
    resource_id: UUID,
    action_perm: Union[str, Permission],
) -> Tuple[bool, Dict[str, Any]]:
    perm_value = _permission_value(action_perm)
    checked_scopes: List[str] = []
    permission_details = {"name": perm_value}

    resource_cache: Dict[UUID, Resource] = {}
    resource = await _get_resource(session, resource_id, resource_cache)
    if not resource:
        return _deny_decision(
            ActorContext(id=actor_principal_id, tenant_id=tenant_id),
            perm_value,
            resource_id,
            "Resource does not exist.",
            {
                "reason": "resource_not_found",
                "checked_scopes": checked_scopes,
                "binding": None,
                "permission": permission_details,
            },
        )

    actor = ActorContext(id=actor_principal_id, tenant_id=tenant_id)
    if resource.tenant_id != tenant_id:
        checked_scopes.append(str(resource.id))
        return _deny_decision(
            actor,
            perm_value,
            resource_id,
            "Actor and resource belong to different tenants.",
            {
                "reason": "tenant_mismatch",
                "actor_tenant_id": str(actor.tenant_id),
                "resource_tenant_id": str(resource.tenant_id),
                "checked_scopes": checked_scopes,
                "binding": None,
                "permission": permission_details,
            },
        )

    chain: List[Resource] = []
    current: Optional[Resource] = resource
    while current:
        chain.append(current)
        checked_scopes.append(str(current.id))
        metadata = current.metadata_json or {}
        if metadata.get("inherit_break") or metadata.get("break_inheritance"):
            break
        if not current.parent_id:
            break
        parent = await _get_resource(session, current.parent_id, resource_cache)
        if not parent:
            break
        current = parent

    scope_ids = [item.id for item in chain]
    bindings_result = await session.scalars(
        select(RoleBinding)
        .where(
            and_(
                RoleBinding.tenant_id == tenant_id,
                RoleBinding.principal_id == actor_principal_id,
                RoleBinding.scope_resource_id.in_(scope_ids),
                RoleBinding.revoked_at.is_(None),
            )
        )
        .order_by(RoleBinding.granted_at.desc())
    )
    bindings = list(bindings_result.all())

    role_names = {binding.role_name for binding in bindings}
    role_perm_types: Dict[str, set[Optional[str]]] = {}
    if role_names:
        perms_result = await session.scalars(
            select(RolePermission).where(
                and_(
                    RolePermission.tenant_id == tenant_id,
                    RolePermission.role_name.in_(role_names),
                    RolePermission.perm_name == perm_value,
                    or_(
                        RolePermission.resource_type.in_({res.type for res in chain}),
                        RolePermission.resource_type == GLOBAL_RESOURCE_TYPE,
                        RolePermission.resource_type.is_(None),
                    ),
                )
            )
        )
        for perm in perms_result.all():
            role_perm_types.setdefault(perm.role_name, set()).add(perm.resource_type)

    def _role_allows(role_name: str, scope_type: str) -> bool:
        perm_types = role_perm_types.get(role_name, set())
        return (
            GLOBAL_RESOURCE_TYPE in perm_types
            or None in perm_types
            or scope_type in perm_types
        )

    allowed_bindings = [
        binding
        for binding in bindings
        if _role_allows(binding.role_name, resource_cache[binding.scope_resource_id].type)
    ]

    object_edges = [
        (_resource_obj(chain[idx].id), _resource_obj(chain[idx + 1].id))
        for idx in range(len(chain) - 1)
    ]

    adapter = CasbinAdapter(
        bindings=bindings,
        allowed_bindings=allowed_bindings,
        tenant_id=str(tenant_id),
        perm_name=perm_value,
        object_edges=object_edges,
    )

    enforcer = casbin.Enforcer(str(_MODEL_PATH), adapter, enable_log=False)
    allowed = enforcer.enforce(
        str(actor_principal_id),
        str(tenant_id),
        _resource_obj(resource_id),
        perm_value,
    )

    binding_match: Optional[RoleBinding] = None
    scope_match: Optional[Resource] = None
    if allowed and allowed_bindings:
        bindings_by_scope: Dict[UUID, List[RoleBinding]] = {}
        for binding in bindings:
            bindings_by_scope.setdefault(binding.scope_resource_id, []).append(binding)

        for scope in chain:
            for binding in bindings_by_scope.get(scope.id, []):
                if _role_allows(binding.role_name, scope.type):
                    binding_match = binding
                    scope_match = scope
                    break
            if binding_match:
                break

    if allowed and binding_match and scope_match:
        binding_info = {
            "id": str(binding_match.id),
            "role": binding_match.role_name,
            "scope_resource_id": str(scope_match.id),
        }
        permission_details = {
            "name": perm_value,
            "resource_type": scope_match.type,
        }
        explanation = DecisionExplanation(
            message="Access granted by role binding.",
            binding_id=binding_match.id,
            role=binding_match.role_name,
            scope_resource_id=scope_match.id,
            inherited=scope_match.id != resource_id,
            details={
                "checked_scopes": checked_scopes,
                "binding": binding_info,
                "permission": permission_details,
            },
        )
        return True, explanation.model_dump(mode="json")

    if allowed:
        explanation = DecisionExplanation(
            message="Access granted by policy.",
            details={
                "checked_scopes": checked_scopes,
                "binding": None,
                "permission": {"name": perm_value, "resource_type": scope_match.type},
            },
        )
        return True, explanation.model_dump(mode="json")

    return _deny_decision(
        actor,
        perm_value,
        resource_id,
        "No matching role binding with required permission found in resource hierarchy.",
        {
            "reason": "binding_not_found",
            "checked_scopes": checked_scopes,
            "binding": None,
            "permission": permission_details,
        },
    )
