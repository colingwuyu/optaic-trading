"""SDK Notifications client for managing user notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID

if TYPE_CHECKING:
    from .client import AsyncPlatformClient


class NotificationsClient:
    """Client for managing user notifications.

    Notifications are created when activities match user subscriptions.
    Users can list, mark read, and manage their notifications.
    """

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def list(
        self,
        *,
        unread_only: bool = False,
        limit: int = 50,
        cursor: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """List notifications for the current user.

        Args:
            unread_only: If true, only return unread notifications
            limit: Maximum number of results (1-200)
            cursor: Pagination cursor
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            NotificationPage with items, next_cursor, and unread_count
        """
        params: Dict[str, Any] = {"limit": limit}

        if unread_only:
            params["unread_only"] = "true"
        if cursor:
            params["cursor"] = cursor

        return await self._client._request(
            "GET",
            "/notifications",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def mark_read(
        self,
        notification_id: str | UUID,
        *,
        read: bool = True,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Mark a notification as read or unread.

        Args:
            notification_id: Notification to update
            read: True to mark as read, False to mark as unread
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Updated notification
        """
        return await self._client._request(
            "PATCH",
            f"/notifications/{notification_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json={"read": read},
        )

    async def mark_all_read(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Mark all unread notifications as read.

        Args:
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Dict with 'marked_count' key
        """
        return await self._client._request(
            "POST",
            "/notifications/mark-all-read",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def unread_count(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get the count of unread notifications.

        Args:
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Dict with 'unread_count' key
        """
        return await self._client._request(
            "GET",
            "/notifications/unread-count",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def get_preferences(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get notification preferences for the current user.

        Args:
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            NotificationPreference with filter_mode, custom_actions, muted
        """
        return await self._client._request(
            "GET",
            "/notifications/preferences",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def update_preferences(
        self,
        *,
        filter_mode: Optional[str] = None,
        custom_actions: Optional[list] = None,
        muted: Optional[bool] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Update notification preferences for the current user.

        Args:
            filter_mode: "all" (all activities), "mutations" (create/update/delete only),
                        or "custom" (user-defined patterns)
            custom_actions: List of action patterns (e.g., ["resource.*", "chat.*"])
            muted: If true, suppress all notifications
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Updated NotificationPreference
        """
        body: Dict[str, Any] = {}
        if filter_mode is not None:
            body["filter_mode"] = filter_mode
        if custom_actions is not None:
            body["custom_actions"] = custom_actions
        if muted is not None:
            body["muted"] = muted

        return await self._client._request(
            "PUT",
            "/notifications/preferences",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=body,
        )
