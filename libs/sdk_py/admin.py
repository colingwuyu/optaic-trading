"""Admin SDK Client - Administrative operations.

Provides admin-level operations:
- create_user_with_space: Create user with Personal Space
- create_team_space: Create Team Space with owner
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

if TYPE_CHECKING:
    from .client import AsyncPlatformClient


def _to_str(value: Optional[str | UUID]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


class AdminClient:
    """Admin operations for user and space management.

    These operations require admin privileges (INVITE_CREATE on TenantRoot).
    """

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def create_user_with_space(
        self,
        display_name: str,
        *,
        email: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a user with their Personal Space.

        This creates:
        1. Principal (user account)
        2. Personal Space
        3. Official + Staging sub-spaces
        4. Owner role on Personal Space
        5. Viewer role on System Space

        Args:
            display_name: User's display name
            email: Optional email address
            principal_id: Override principal for auth (must be admin)
            tenant_id: Override tenant for auth

        Returns:
            UserWithSpaceOut with principal and space IDs
        """
        payload = _drop_none(
            {
                "display_name": display_name,
                "email": email,
            }
        )
        return await self._client._request(
            "POST",
            "/users",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def create_team_space(
        self,
        name: str,
        owner_principal_id: str | UUID,
        *,
        member_principal_ids: Optional[List[str | UUID]] = None,
        description: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a Team Space with an assigned owner.

        This creates:
        1. Team Space
        2. Official + Staging sub-spaces
        3. Owner role for owner_principal_id
        4. Operator role for optional members

        Args:
            name: Team name
            owner_principal_id: Principal who will own this team space
            member_principal_ids: Optional list of members to add as operators
            description: Optional description
            principal_id: Override principal for auth (must be admin)
            tenant_id: Override tenant for auth

        Returns:
            SpaceOut with space and subspace IDs
        """
        members = None
        if member_principal_ids:
            members = [str(m) for m in member_principal_ids]

        payload = _drop_none(
            {
                "name": name,
                "owner_principal_id": str(owner_principal_id),
                "member_principal_ids": members,
                "description": description,
            }
        )
        return await self._client._request(
            "POST",
            "/spaces/team",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def create_custom_subspace(
        self,
        space_id: str | UUID,
        name: str,
        *,
        description: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a custom subspace under a space.

        Users can create additional subspaces beyond Official and Staging.

        Args:
            space_id: Parent Space ID
            name: Subspace name
            description: Optional description
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            SubspaceOut with subspace info
        """
        payload = _drop_none(
            {
                "name": name,
                "description": description,
            }
        )
        return await self._client._request(
            "POST",
            f"/spaces/{space_id}/subspaces",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )
