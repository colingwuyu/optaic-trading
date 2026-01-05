"""Governance client for resource governance operations.

Provides SDK methods for:
- Copy (reference): Same artifact, no RBAC change
- Branch: Copy files, actor=owner, source_owner=viewer
- Transfer: Request/accept workflow
- Promote: To staging, approval-based auto-move to official
- Merge: Branch artifact replaces ancestor
- Lineage: Query resource derivation history
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


class GovernanceClient:
    """Client for resource governance operations.

    Governance operations include copy, branch, transfer, promote, and merge.
    Each operation has specific artifact handling and RBAC mutations.

    Resource Type Rules:
    - Flow resources (runs): View-only, no governance actions
    - Scope resources (Projects): Copy, transfer, promote (no branch/merge)
    - Definition/Instance: All governance actions allowed
    """

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    # =========================================================================
    # Core Governance Operations
    # =========================================================================

    async def copy(
        self,
        resource_id: str | UUID,
        target_parent_id: str | UUID,
        *,
        name: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Copy a resource by reference (no file copy).

        Creates a new resource that references the same artifact.
        RBAC bindings are NOT changed.

        Args:
            resource_id: Source resource to copy
            target_parent_id: Target parent (must be a Project)
            name: Optional new name (defaults to "Copy of {source}")
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Created resource info with operation="copy"
        """
        payload = _drop_none(
            {
                "target_parent_id": str(target_parent_id),
                "name": name,
            }
        )
        return await self._client._request(
            "POST",
            f"/governance/resources/{resource_id}/copy",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def branch(
        self,
        resource_id: str | UUID,
        target_parent_id: str | UUID,
        *,
        name: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Branch a resource with file copy.

        Creates a new resource with COPIED artifact files.
        RBAC mutations: actor=owner, source_owner=viewer.

        Not allowed for Flow resources or Scope resources (Projects).

        Args:
            resource_id: Source resource to branch
            target_parent_id: Target parent (must be a Project)
            name: Optional new name (defaults to "Branch of {source}")
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Created resource info with operation="branch"
        """
        payload = _drop_none(
            {
                "target_parent_id": str(target_parent_id),
                "name": name,
            }
        )
        return await self._client._request(
            "POST",
            f"/governance/resources/{resource_id}/branch",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def promote(
        self,
        resource_id: str | UUID,
        target_space_id: str | UUID,
        team_principal_id: str | UUID,
        *,
        name: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Promote a resource to a team's staging subspace.

        Creates a copy in the team's staging subspace with a PromotionRequest.
        Upon approval, resource auto-moves to official subspace.

        RBAC mutations: team=owner, promoter=delegator.

        Args:
            resource_id: Source resource to promote
            target_space_id: Target team space
            team_principal_id: Team principal (new owner)
            name: Optional new name
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Created resource info with promotion_request_id
        """
        payload = _drop_none(
            {
                "target_space_id": str(target_space_id),
                "team_principal_id": str(team_principal_id),
                "name": name,
            }
        )
        return await self._client._request(
            "POST",
            f"/governance/resources/{resource_id}/promote",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def merge(
        self,
        source_id: str | UUID,
        target_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Merge a branch back to its ancestor.

        Replaces the ancestor's artifact with the branch's artifact.
        The source (branch) is marked as merged.

        Requires: source must be a branch_of target.

        Args:
            source_id: Branch resource (source of merge)
            target_id: Ancestor resource (target to update)
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Merge result with target_id, source_id, contributor_id
        """
        payload = {"target_id": str(target_id)}
        return await self._client._request(
            "POST",
            f"/governance/resources/{source_id}/merge",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    # =========================================================================
    # Transfer Request Workflow
    # =========================================================================

    async def create_transfer_request(
        self,
        resource_id: str | UUID,
        recipient_id: str | UUID,
        *,
        message: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a transfer request for a resource.

        Initiates the transfer workflow:
        1. Sender creates request
        2. Recipient receives notification
        3. Recipient accepts/rejects with destination project

        Args:
            resource_id: Resource to transfer
            recipient_id: Proposed new owner
            message: Optional message to recipient
            principal_id: Override principal (must be current owner)
            tenant_id: Override tenant for auth

        Returns:
            Transfer request info with status="pending"
        """
        payload = _drop_none(
            {
                "recipient_id": str(recipient_id),
                "message": message,
            }
        )
        return await self._client._request(
            "POST",
            f"/governance/resources/{resource_id}/transfer-request",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def accept_transfer(
        self,
        transfer_request_id: str | UUID,
        destination_project_id: str | UUID,
        *,
        response_message: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Accept a transfer request and move resource to destination project.

        Completes the transfer:
        1. Validates recipient and destination
        2. Moves resource to destination project
        3. Updates ownership and RBAC

        Args:
            transfer_request_id: Transfer request to accept
            destination_project_id: Project to place the resource
            response_message: Optional response message
            principal_id: Override principal (must be recipient)
            tenant_id: Override tenant for auth

        Returns:
            Updated resource info with new owner
        """
        payload = _drop_none(
            {
                "destination_project_id": str(destination_project_id),
                "response_message": response_message,
            }
        )
        return await self._client._request(
            "POST",
            f"/governance/transfers/{transfer_request_id}/accept",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def reject_transfer(
        self,
        transfer_request_id: str | UUID,
        *,
        response_message: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Reject a transfer request.

        Args:
            transfer_request_id: Transfer request to reject
            response_message: Optional rejection reason
            principal_id: Override principal (must be recipient)
            tenant_id: Override tenant for auth

        Returns:
            Transfer request with status="rejected"
        """
        payload = _drop_none({"response_message": response_message})
        return await self._client._request(
            "POST",
            f"/governance/transfers/{transfer_request_id}/reject",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def cancel_transfer(
        self,
        transfer_request_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Cancel a transfer request (by sender).

        Args:
            transfer_request_id: Transfer request to cancel
            principal_id: Override principal (must be sender)
            tenant_id: Override tenant for auth

        Returns:
            Transfer request with status="cancelled"
        """
        return await self._client._request(
            "POST",
            f"/governance/transfers/{transfer_request_id}/cancel",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def transfer(
        self,
        resource_id: str | UUID,
        target_owner_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Transfer ownership directly (legacy, use request/accept workflow).

        DEPRECATED: Use create_transfer_request + accept_transfer instead.

        Args:
            resource_id: Resource to transfer
            target_owner_id: New owner principal
            principal_id: Override principal (must be current owner)
            tenant_id: Override tenant for auth

        Returns:
            Updated resource info
        """
        payload = {"target_owner_id": str(target_owner_id)}
        return await self._client._request(
            "POST",
            f"/governance/resources/{resource_id}/transfer",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    # =========================================================================
    # Promotion Approval
    # =========================================================================

    async def approve_promotion(
        self,
        promotion_request_id: str | UUID,
        *,
        comment: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Approve a promotion request.

        When all required approvals are met, the resource is:
        1. Moved from staging to official subspace
        2. Status updated to 'active'

        Args:
            promotion_request_id: Promotion request to approve
            comment: Optional approval comment
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Approval result with approval_count and status
        """
        payload = _drop_none({"comment": comment})
        return await self._client._request(
            "POST",
            f"/governance/promotions/{promotion_request_id}/approve",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    # =========================================================================
    # Lineage Queries
    # =========================================================================

    async def get_lineage(
        self,
        resource_id: str | UUID,
        *,
        direction: str = "upstream",
        edge_types: Optional[List[str]] = None,
        max_depth: int = 10,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get resource lineage (ancestors or descendants).

        Args:
            resource_id: Starting resource
            direction: "upstream" (ancestors) or "downstream" (descendants)
            edge_types: Filter by types (copy_of, branch_of, promoted_from, merged_from)
            max_depth: Maximum traversal depth (1-50)
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Lineage with entries list
        """
        params = _drop_none(
            {
                "direction": direction,
                "edge_types": ",".join(edge_types) if edge_types else None,
                "max_depth": max_depth,
            }
        )
        return await self._client._request(
            "GET",
            f"/governance/resources/{resource_id}/lineage",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )
