"""SDK Audit client for querying audit logs."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID

if TYPE_CHECKING:
    from .client import AsyncPlatformClient


class AuditClient:
    """Client for querying audit logs.

    Audit logs provide a complete audit trail of all activities
    in the system. This is typically admin-only access.
    """

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def search(
        self,
        *,
        actor_principal_id: Optional[str | UUID] = None,
        resource_id: Optional[str | UUID] = None,
        action: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Search audit logs with filtering.

        Args:
            actor_principal_id: Filter by actor who performed the action
            resource_id: Filter by resource ID
            action: Filter by action type (e.g., resource.created)
            after: Return entries after this timestamp
            before: Return entries before this timestamp
            limit: Maximum number of results (1-200)
            cursor: Pagination cursor
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            AuditLogPage with items and next_cursor
        """
        params: Dict[str, Any] = {"limit": limit}

        if actor_principal_id:
            params["actor_principal_id"] = str(actor_principal_id)
        if resource_id:
            params["resource_id"] = str(resource_id)
        if action:
            params["action"] = action
        if after:
            params["after"] = after.isoformat()
        if before:
            params["before"] = before.isoformat()
        if cursor:
            params["cursor"] = cursor

        return await self._client._request(
            "GET",
            "/audit-logs",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def count(
        self,
        *,
        actor_principal_id: Optional[str | UUID] = None,
        resource_id: Optional[str | UUID] = None,
        action: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Count audit log entries matching the filters.

        Args:
            actor_principal_id: Filter by actor who performed the action
            resource_id: Filter by resource ID
            action: Filter by action type
            after: Return entries after this timestamp
            before: Return entries before this timestamp
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Dict with 'count' key
        """
        params: Dict[str, Any] = {}

        if actor_principal_id:
            params["actor_principal_id"] = str(actor_principal_id)
        if resource_id:
            params["resource_id"] = str(resource_id)
        if action:
            params["action"] = action
        if after:
            params["after"] = after.isoformat()
        if before:
            params["before"] = before.isoformat()

        return await self._client._request(
            "GET",
            "/audit-logs/count",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )
