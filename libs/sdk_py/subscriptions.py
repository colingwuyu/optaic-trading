"""SDK Subscriptions client for resource subscription management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

if TYPE_CHECKING:
    from .client import AsyncPlatformClient


class SubscriptionsClient:
    """Client for managing resource subscriptions.

    Subscriptions allow users to receive activity notifications for resources
    they're interested in, even if they don't have direct RBAC permissions.
    """

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def create(
        self,
        resource_id: str | UUID,
        scope: str,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a subscription to a resource.

        Args:
            resource_id: Resource to subscribe to
            scope: Subscription scope ("resource" or "descendants")
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Created subscription
        """
        payload = {
            "resource_id": str(resource_id),
            "scope": scope,
        }
        return await self._client._request(
            "POST",
            "/subscriptions",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def revoke(
        self,
        subscription_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Revoke (soft-delete) a subscription.

        Args:
            subscription_id: Subscription to revoke
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Revoked subscription with revoked_at timestamp
        """
        return await self._client._request(
            "DELETE",
            f"/subscriptions/{subscription_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def list(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> List[Dict[str, Any]]:
        """List active subscriptions for the current user.

        Args:
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            List of active subscriptions
        """
        return await self._client._request(
            "GET",
            "/subscriptions",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )
