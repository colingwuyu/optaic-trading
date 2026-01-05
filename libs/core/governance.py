"""Governance Service for resource operations.

Manages resource governance operations with proper RBAC mutations:
- Copy (reference): Same artifact_ref, no RBAC change
- Branch: New artifact_ref (copied files), actor=owner, source_owner=viewer
- Transfer: Request/accept workflow, recipient chooses project
- Promote: To staging, approval-based auto-move to official
- Merge: Branch artifact replaces ancestor, contributor credit

Resource Type Rules:
- Flow resources (runs): View-only, no governance actions
- Scope resources (Projects): Copy, transfer, promote (no branch/merge)
- Definition/Instance: All governance actions allowed

Each operation:
1. Validates resource type allows the action
2. Validates placement (target parent type)
3. Creates/modifies resources
4. Creates lineage edges
5. Applies RBAC template mutations
6. Emits activity envelope for audit trail
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.core.artifacts import ArtifactManager
from libs.core.rbac.models import ActorContext
from libs.core.resource_types import GovernanceAction, ResourceTypes
from libs.db.models.merge import Approval
from libs.db.models.promotion import PromotionRequest, RbacTemplate
from libs.db.models.rbac import RoleBinding
from libs.db.models.resource import Resource, ResourceEdge
from libs.db.models.transfer import TransferRequest

logger = structlog.get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Ensure datetime is timezone-aware (assume UTC if naive).

    SQLite may return naive datetimes even with DateTime(timezone=True).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class GovernanceError(Exception):
    """Base exception for governance errors."""

    pass


class ResourceTypeError(GovernanceError):
    """Error when resource type does not allow the action."""

    pass


class PlacementError(GovernanceError):
    """Error when resource placement is invalid."""

    pass


class GovernanceService:
    """Service for resource governance operations with RBAC mutations.

    This service implements the governance operations that mutate both
    resources and their RBAC bindings according to predefined templates.

    Resource Type Rules:
    - Flow resources: View-only sharing (no copy, transfer, promote, etc.)
    - Scope resources (Projects): Copy, transfer, promote (no branch/merge)
    - Definition/Instance resources: All governance operations
    """

    def __init__(
        self,
        artifact_manager: ArtifactManager | None = None,
        transfer_expiry_days: int = 7,
    ) -> None:
        """Initialize the governance service.

        Args:
            artifact_manager: Optional artifact manager for file operations.
                            If not provided, a default manager will be created.
            transfer_expiry_days: Days until transfer requests expire.
        """
        self._artifact_manager = artifact_manager or ArtifactManager()
        self._transfer_expiry_days = transfer_expiry_days

    # =========================================================================
    # Validation Helpers
    # =========================================================================

    def _validate_action(
        self,
        resource: Resource,
        action: GovernanceAction,
    ) -> None:
        """Validate that an action is allowed for a resource type.

        Args:
            resource: Resource to validate
            action: Governance action to perform

        Raises:
            ResourceTypeError: If action is not allowed
        """
        if not ResourceTypes.is_action_allowed(resource.type, action):
            allowed = ResourceTypes.get_allowed_actions(resource.type)
            raise ResourceTypeError(
                f"Action '{action.value}' not allowed for resource type '{resource.type}'. "
                f"Allowed actions: {[a.value for a in allowed]}"
            )

    async def _validate_placement(
        self,
        session: AsyncSession,
        resource_type: str,
        parent_id: UUID,
    ) -> Resource:
        """Validate placement and return the parent resource.

        Args:
            session: Database session
            resource_type: Type of resource being placed
            parent_id: Parent resource ID

        Returns:
            Parent resource

        Raises:
            PlacementError: If placement is invalid
        """
        parent = await session.get(Resource, parent_id)
        if not parent:
            raise PlacementError(f"Parent resource {parent_id} not found")

        is_valid, error = ResourceTypes.validate_placement(resource_type, parent.type)
        if not is_valid:
            raise PlacementError(error)

        return parent

    # =========================================================================
    # RBAC Template Management
    # =========================================================================

    async def get_rbac_template(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        name: str,
    ) -> RbacTemplate | None:
        """Get an RBAC template by name.

        Args:
            session: Database session
            tenant_id: Tenant ID
            name: Template name (e.g., "branch", "promote", "transfer")

        Returns:
            RbacTemplate if found, None otherwise
        """
        result = await session.execute(
            select(RbacTemplate).where(
                RbacTemplate.tenant_id == tenant_id,
                RbacTemplate.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def create_rbac_template(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        policy: dict[str, Any],
    ) -> RbacTemplate:
        """Create a new RBAC template.

        Args:
            session: Database session
            actor: Actor context
            name: Template name
            policy: RBAC policy definition

        Returns:
            Created template
        """
        template = RbacTemplate(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            name=name,
            policy=policy,
        )
        session.add(template)
        return template

    async def apply_rbac_template(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        resource_id: UUID,
        template: RbacTemplate,
        context: dict[str, UUID],
    ) -> list[RoleBinding]:
        """Apply an RBAC template to a resource.

        The template policy defines role bindings to create/modify.
        Context provides UUIDs for template variables:
        - actor_id: The user performing the operation
        - source_owner_id: Original owner of the source resource
        - target_owner_id: New owner of the target resource
        - team_id: Team principal for promote operations

        Args:
            session: Database session
            tenant_id: Tenant ID
            resource_id: Resource to apply template to
            template: RBAC template with policy
            context: Variable values for template substitution

        Returns:
            List of created role bindings
        """
        created_bindings: list[RoleBinding] = []
        policy = template.policy

        # Process each binding in the policy
        for binding_spec in policy.get("bindings", []):
            principal_var = binding_spec.get("principal")
            role = binding_spec.get("role")

            if not principal_var or not role:
                continue

            # Resolve principal from context
            principal_id = context.get(principal_var)
            if not principal_id:
                logger.warning(
                    "governance.template_missing_context",
                    template_name=template.name,
                    missing_var=principal_var,
                )
                continue

            # Check for existing binding
            existing = await session.execute(
                select(RoleBinding).where(
                    RoleBinding.tenant_id == tenant_id,
                    RoleBinding.principal_id == principal_id,
                    RoleBinding.scope_resource_id == resource_id,
                    RoleBinding.role_name == role,
                    RoleBinding.revoked_at.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                continue  # Binding already exists

            # Create new binding
            binding = RoleBinding(
                id=uuid4(),
                tenant_id=tenant_id,
                principal_id=principal_id,
                scope_resource_id=resource_id,
                role_name=role,
                granted_by=context.get("actor_id", principal_id),
            )
            session.add(binding)
            created_bindings.append(binding)

        # Process revocations
        for revocation_spec in policy.get("revocations", []):
            principal_var = revocation_spec.get("principal")
            role = revocation_spec.get("role")

            if not principal_var:
                continue

            principal_id = context.get(principal_var)
            if not principal_id:
                continue

            # Find bindings to revoke
            query = select(RoleBinding).where(
                RoleBinding.tenant_id == tenant_id,
                RoleBinding.principal_id == principal_id,
                RoleBinding.scope_resource_id == resource_id,
                RoleBinding.revoked_at.is_(None),
            )
            if role:
                query = query.where(RoleBinding.role_name == role)

            result = await session.execute(query)
            for binding in result.scalars().all():
                binding.revoked_at = utcnow()

        return created_bindings

    # =========================================================================
    # Governance Operations
    # =========================================================================

    async def copy_resource(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        source_id: UUID,
        target_parent_id: UUID,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Copy a resource by reference (no file copy).

        Copy creates a new resource that references the same artifact.
        RBAC bindings are NOT changed - user keeps their existing role.

        Args:
            session: Database session
            actor: Actor context
            source_id: Source resource ID
            target_parent_id: Target parent resource ID (must be a Project)
            name: Optional new name (defaults to source name)

        Returns:
            Created resource info

        Raises:
            ResourceTypeError: If resource type doesn't allow copy
            PlacementError: If target parent is invalid
        """
        # Load source resource
        source = await session.get(Resource, source_id)
        if not source or source.tenant_id != actor.tenant_id:
            raise ValueError(f"Source resource {source_id} not found")

        # Validate action is allowed
        self._validate_action(source, GovernanceAction.COPY)

        # Validate placement
        await self._validate_placement(session, source.type, target_parent_id)

        # Create new resource with same artifact_ref
        new_id = uuid4()
        new_resource = Resource(
            id=new_id,
            tenant_id=actor.tenant_id,
            type=source.type,
            parent_id=target_parent_id,
            owner_principal_id=actor.id,  # Actor becomes owner
            space_kind=source.space_kind,
            subspace_kind=source.subspace_kind,
            name=name or f"Copy of {source.name}",
            status="active",
            metadata_json=source.metadata_json.copy() if source.metadata_json else {},
            artifact_ref=source.artifact_ref,  # Same artifact reference
        )
        session.add(new_resource)

        # Create lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=new_id,
            dst_resource_id=source_id,
            edge_type="copy_of",
            created_by_principal_id=actor.id,
        )
        session.add(edge)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=new_id,
            resource_type=source.type,
            action="resource.copied",
            payload={
                "source_id": str(source_id),
                "target_parent_id": str(target_parent_id),
                "name": new_resource.name,
                "artifact_ref": str(source.artifact_ref)
                if source.artifact_ref
                else None,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.resource_copied",
            source_id=str(source_id),
            target_id=str(new_id),
            actor_id=str(actor.id),
        )

        return {
            "id": str(new_id),
            "name": new_resource.name,
            "type": new_resource.type,
            "source_id": str(source_id),
            "artifact_ref": str(source.artifact_ref) if source.artifact_ref else None,
            "operation": "copy",
        }

    async def branch_resource(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        source_id: UUID,
        target_parent_id: UUID,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Branch a resource with file copy.

        Branch creates a new resource with a COPY of the artifact files.
        Only allowed for Definition and Instance resources (not Projects, not Flows).

        RBAC mutations:
        - Actor becomes owner of new resource
        - Source owner gets viewer role on new resource

        Args:
            session: Database session
            actor: Actor context
            source_id: Source resource ID
            target_parent_id: Target parent resource ID (must be a Project)
            name: Optional new name

        Returns:
            Created resource info

        Raises:
            ResourceTypeError: If resource type doesn't allow branch
            PlacementError: If target parent is invalid
        """
        # Load source resource
        source = await session.get(Resource, source_id)
        if not source or source.tenant_id != actor.tenant_id:
            raise ValueError(f"Source resource {source_id} not found")

        # Validate action is allowed (Flow and Scope resources can't branch)
        self._validate_action(source, GovernanceAction.BRANCH)

        # Validate placement
        await self._validate_placement(session, source.type, target_parent_id)

        # Copy artifact files if present
        new_artifact_ref = None
        if source.artifact_ref:
            new_artifact_ref = self._artifact_manager.copy_artifact(source.artifact_ref)

        # Create new resource
        new_id = uuid4()
        new_resource = Resource(
            id=new_id,
            tenant_id=actor.tenant_id,
            type=source.type,
            parent_id=target_parent_id,
            owner_principal_id=actor.id,  # Actor becomes owner
            space_kind="personal",  # Branches are in personal space
            subspace_kind="custom",
            name=name or f"Branch of {source.name}",
            status="active",
            metadata_json=source.metadata_json.copy() if source.metadata_json else {},
            artifact_ref=new_artifact_ref,
        )
        session.add(new_resource)

        # Create lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=new_id,
            dst_resource_id=source_id,
            edge_type="branch_of",
            created_by_principal_id=actor.id,
        )
        session.add(edge)

        # Flush to satisfy FK constraint before creating role bindings
        await session.flush()

        # Apply RBAC: actor=owner, source_owner=viewer
        owner_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=actor.id,
            scope_resource_id=new_id,
            role_name="owner",
            granted_by=actor.id,
        )
        session.add(owner_binding)

        # Create viewer binding for source owner (if different from actor)
        if source.owner_principal_id != actor.id:
            viewer_binding = RoleBinding(
                id=uuid4(),
                tenant_id=actor.tenant_id,
                principal_id=source.owner_principal_id,
                scope_resource_id=new_id,
                role_name="viewer",
                granted_by=actor.id,
            )
            session.add(viewer_binding)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=new_id,
            resource_type=source.type,
            action="resource.branched",
            payload={
                "source_id": str(source_id),
                "target_parent_id": str(target_parent_id),
                "name": new_resource.name,
                "artifact_ref": str(new_artifact_ref) if new_artifact_ref else None,
                "source_artifact_ref": str(source.artifact_ref)
                if source.artifact_ref
                else None,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.resource_branched",
            source_id=str(source_id),
            target_id=str(new_id),
            actor_id=str(actor.id),
        )

        return {
            "id": str(new_id),
            "name": new_resource.name,
            "type": new_resource.type,
            "source_id": str(source_id),
            "artifact_ref": str(new_artifact_ref) if new_artifact_ref else None,
            "operation": "branch",
        }

    # =========================================================================
    # Transfer Request/Accept Workflow
    # =========================================================================

    async def create_transfer_request(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        resource_id: UUID,
        recipient_id: UUID,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Create a transfer request for a resource.

        Initiates the transfer workflow:
        1. Sender creates request
        2. Recipient receives notification
        3. Recipient accepts/rejects with destination project

        Args:
            session: Database session
            actor: Actor context (sender, must be current owner)
            resource_id: Resource to transfer
            recipient_id: Proposed new owner
            message: Optional message to recipient

        Returns:
            Created transfer request info

        Raises:
            ResourceTypeError: If resource type doesn't allow transfer
            ValueError: If sender is not the owner or pending request exists
        """
        # Load resource
        resource = await session.get(Resource, resource_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Resource {resource_id} not found")

        # Validate action is allowed
        self._validate_action(resource, GovernanceAction.TRANSFER)

        # Verify actor is current owner
        if resource.owner_principal_id != actor.id:
            raise ValueError("Only the owner can transfer a resource")

        # Check for existing pending transfer
        existing = await session.execute(
            select(TransferRequest).where(
                TransferRequest.resource_id == resource_id,
                TransferRequest.status == "pending",
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(
                f"A pending transfer request already exists for {resource_id}"
            )

        # Create transfer request
        expires_at = utcnow() + timedelta(days=self._transfer_expiry_days)
        transfer_request = TransferRequest(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            resource_id=resource_id,
            sender_id=actor.id,
            recipient_id=recipient_id,
            message=message,
            status="pending",
            expires_at=expires_at,
        )
        session.add(transfer_request)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type=resource.type,
            action="transfer.requested",
            payload={
                "transfer_request_id": str(transfer_request.id),
                "recipient_id": str(recipient_id),
                "message": message,
                "expires_at": expires_at.isoformat(),
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.transfer_requested",
            resource_id=str(resource_id),
            sender_id=str(actor.id),
            recipient_id=str(recipient_id),
        )

        return {
            "id": str(transfer_request.id),
            "resource_id": str(resource_id),
            "sender_id": str(actor.id),
            "recipient_id": str(recipient_id),
            "status": "pending",
            "expires_at": expires_at.isoformat(),
            "operation": "transfer_request",
        }

    async def accept_transfer(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        transfer_request_id: UUID,
        destination_project_id: UUID,
        response_message: str | None = None,
    ) -> dict[str, Any]:
        """Accept a transfer request and move resource to destination project.

        Completes the transfer:
        1. Validates recipient and destination
        2. Moves resource to destination project
        3. Updates ownership and RBAC
        4. Marks request as accepted

        Args:
            session: Database session
            actor: Actor context (recipient)
            transfer_request_id: Transfer request to accept
            destination_project_id: Project to place the resource
            response_message: Optional response message

        Returns:
            Transfer result info

        Raises:
            ValueError: If request not found, not pending, or actor is not recipient
            PlacementError: If destination project is invalid
        """
        # Load transfer request
        transfer_request = await session.get(TransferRequest, transfer_request_id)
        if not transfer_request or transfer_request.tenant_id != actor.tenant_id:
            raise ValueError(f"Transfer request {transfer_request_id} not found")

        # Verify actor is the recipient
        if transfer_request.recipient_id != actor.id:
            raise ValueError("Only the recipient can accept a transfer request")

        # Verify request is pending
        if transfer_request.status != "pending":
            raise ValueError(
                f"Transfer request is {transfer_request.status}, not pending"
            )

        # Check expiry (handle naive datetime from SQLite)
        expires_at = _ensure_aware(transfer_request.expires_at)
        if expires_at and expires_at < utcnow():
            transfer_request.status = "expired"
            raise ValueError("Transfer request has expired")

        # Load resource
        resource = await session.get(Resource, transfer_request.resource_id)
        if not resource:
            raise ValueError(f"Resource {transfer_request.resource_id} not found")

        # Validate destination project
        await self._validate_placement(session, resource.type, destination_project_id)

        # Get destination project details
        destination = await session.get(Resource, destination_project_id)
        if not destination:
            raise PlacementError(
                f"Destination project {destination_project_id} not found"
            )

        previous_owner_id = resource.owner_principal_id
        previous_parent_id = resource.parent_id

        # Update resource: owner, parent, space/subspace
        resource.owner_principal_id = actor.id
        resource.parent_id = destination_project_id
        resource.space_kind = destination.space_kind
        resource.subspace_kind = destination.subspace_kind

        # Update transfer request
        transfer_request.status = "accepted"
        transfer_request.destination_project_id = destination_project_id
        transfer_request.response_message = response_message
        transfer_request.resolved_at = utcnow()

        # Create lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=resource.id,
            dst_resource_id=resource.id,  # Self-reference for transfer
            edge_type="transferred_from",
            created_by_principal_id=actor.id,
        )
        session.add(edge)

        # RBAC mutations
        # Revoke previous owner
        prev_bindings = await session.execute(
            select(RoleBinding).where(
                RoleBinding.tenant_id == actor.tenant_id,
                RoleBinding.principal_id == previous_owner_id,
                RoleBinding.scope_resource_id == resource.id,
                RoleBinding.role_name == "owner",
                RoleBinding.revoked_at.is_(None),
            )
        )
        for binding in prev_bindings.scalars().all():
            binding.revoked_at = utcnow()

        # Grant owner to recipient
        new_owner_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=actor.id,
            scope_resource_id=resource.id,
            role_name="owner",
            granted_by=actor.id,
        )
        session.add(new_owner_binding)

        # Grant viewer to previous owner
        viewer_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=previous_owner_id,
            scope_resource_id=resource.id,
            role_name="viewer",
            granted_by=actor.id,
        )
        session.add(viewer_binding)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource.id,
            resource_type=resource.type,
            action="transfer.accepted",
            payload={
                "transfer_request_id": str(transfer_request_id),
                "previous_owner_id": str(previous_owner_id),
                "previous_parent_id": str(previous_parent_id)
                if previous_parent_id
                else None,
                "destination_project_id": str(destination_project_id),
                "response_message": response_message,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.transfer_accepted",
            transfer_request_id=str(transfer_request_id),
            resource_id=str(resource.id),
            from_owner=str(previous_owner_id),
            to_owner=str(actor.id),
        )

        return {
            "id": str(resource.id),
            "name": resource.name,
            "type": resource.type,
            "previous_owner_id": str(previous_owner_id),
            "owner_id": str(actor.id),
            "destination_project_id": str(destination_project_id),
            "operation": "transfer_accepted",
        }

    async def reject_transfer(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        transfer_request_id: UUID,
        response_message: str | None = None,
    ) -> dict[str, Any]:
        """Reject a transfer request.

        Args:
            session: Database session
            actor: Actor context (recipient)
            transfer_request_id: Transfer request to reject
            response_message: Optional rejection reason

        Returns:
            Rejection result info
        """
        # Load transfer request
        transfer_request = await session.get(TransferRequest, transfer_request_id)
        if not transfer_request or transfer_request.tenant_id != actor.tenant_id:
            raise ValueError(f"Transfer request {transfer_request_id} not found")

        # Verify actor is the recipient
        if transfer_request.recipient_id != actor.id:
            raise ValueError("Only the recipient can reject a transfer request")

        # Verify request is pending
        if transfer_request.status != "pending":
            raise ValueError(
                f"Transfer request is {transfer_request.status}, not pending"
            )

        # Update transfer request
        transfer_request.status = "rejected"
        transfer_request.response_message = response_message
        transfer_request.resolved_at = utcnow()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=transfer_request.resource_id,
            resource_type="Resource",  # Generic
            action="transfer.rejected",
            payload={
                "transfer_request_id": str(transfer_request_id),
                "sender_id": str(transfer_request.sender_id),
                "response_message": response_message,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.transfer_rejected",
            transfer_request_id=str(transfer_request_id),
            resource_id=str(transfer_request.resource_id),
            recipient_id=str(actor.id),
        )

        return {
            "id": str(transfer_request_id),
            "resource_id": str(transfer_request.resource_id),
            "status": "rejected",
            "response_message": response_message,
            "operation": "transfer_rejected",
        }

    async def cancel_transfer(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        transfer_request_id: UUID,
    ) -> dict[str, Any]:
        """Cancel a transfer request (by sender).

        Args:
            session: Database session
            actor: Actor context (sender)
            transfer_request_id: Transfer request to cancel

        Returns:
            Cancellation result info
        """
        # Load transfer request
        transfer_request = await session.get(TransferRequest, transfer_request_id)
        if not transfer_request or transfer_request.tenant_id != actor.tenant_id:
            raise ValueError(f"Transfer request {transfer_request_id} not found")

        # Verify actor is the sender
        if transfer_request.sender_id != actor.id:
            raise ValueError("Only the sender can cancel a transfer request")

        # Verify request is pending
        if transfer_request.status != "pending":
            raise ValueError(
                f"Transfer request is {transfer_request.status}, not pending"
            )

        # Update transfer request
        transfer_request.status = "cancelled"
        transfer_request.resolved_at = utcnow()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=transfer_request.resource_id,
            resource_type="Resource",
            action="transfer.cancelled",
            payload={
                "transfer_request_id": str(transfer_request_id),
                "recipient_id": str(transfer_request.recipient_id),
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.transfer_cancelled",
            transfer_request_id=str(transfer_request_id),
            resource_id=str(transfer_request.resource_id),
        )

        return {
            "id": str(transfer_request_id),
            "resource_id": str(transfer_request.resource_id),
            "status": "cancelled",
            "operation": "transfer_cancelled",
        }

    # Legacy direct transfer (kept for backward compatibility, use request/accept instead)
    async def transfer_resource(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        resource_id: UUID,
        target_owner_id: UUID,
    ) -> dict[str, Any]:
        """Transfer ownership of a resource directly (legacy).

        DEPRECATED: Use create_transfer_request + accept_transfer for proper workflow.

        Transfer changes ownership without copying files.
        RBAC mutations:
        - Target becomes owner
        - Previous owner becomes viewer

        Args:
            session: Database session
            actor: Actor context (must be current owner)
            resource_id: Resource to transfer
            target_owner_id: New owner principal ID

        Returns:
            Updated resource info
        """
        # Load resource
        resource = await session.get(Resource, resource_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Resource {resource_id} not found")

        # Validate action is allowed
        self._validate_action(resource, GovernanceAction.TRANSFER)

        # Verify actor is current owner
        if resource.owner_principal_id != actor.id:
            raise ValueError("Only the owner can transfer a resource")

        previous_owner_id = resource.owner_principal_id

        # Update ownership
        resource.owner_principal_id = target_owner_id

        # Create lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=resource_id,
            dst_resource_id=resource_id,  # Self-reference for transfer
            edge_type="transferred_from",
            created_by_principal_id=actor.id,
        )
        session.add(edge)

        # RBAC mutations: revoke owner from previous, grant owner to target
        prev_bindings = await session.execute(
            select(RoleBinding).where(
                RoleBinding.tenant_id == actor.tenant_id,
                RoleBinding.principal_id == previous_owner_id,
                RoleBinding.scope_resource_id == resource_id,
                RoleBinding.role_name == "owner",
                RoleBinding.revoked_at.is_(None),
            )
        )
        for binding in prev_bindings.scalars().all():
            binding.revoked_at = utcnow()

        # Grant owner to target
        new_owner_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=target_owner_id,
            scope_resource_id=resource_id,
            role_name="owner",
            granted_by=actor.id,
        )
        session.add(new_owner_binding)

        # Grant viewer to previous owner
        viewer_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=previous_owner_id,
            scope_resource_id=resource_id,
            role_name="viewer",
            granted_by=actor.id,
        )
        session.add(viewer_binding)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type=resource.type,
            action="resource.transferred",
            payload={
                "previous_owner_id": str(previous_owner_id),
                "target_owner_id": str(target_owner_id),
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.resource_transferred",
            resource_id=str(resource_id),
            from_owner=str(previous_owner_id),
            to_owner=str(target_owner_id),
            actor_id=str(actor.id),
        )

        return {
            "id": str(resource_id),
            "name": resource.name,
            "type": resource.type,
            "previous_owner_id": str(previous_owner_id),
            "owner_id": str(target_owner_id),
            "operation": "transfer",
        }

    # =========================================================================
    # Promote to Staging with Approval Workflow
    # =========================================================================

    async def promote_resource(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        source_id: UUID,
        target_space_id: UUID,
        team_principal_id: UUID,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Promote a resource to team's staging subspace.

        Promotion workflow:
        1. Resource is copied to team's STAGING subspace
        2. PromotionRequest is created for approval
        3. Upon approval, resource is auto-moved to OFFICIAL subspace

        RBAC mutations (in staging):
        - Team becomes owner
        - Promoter gets delegator role

        Args:
            session: Database session
            actor: Actor context (promoter)
            source_id: Source resource to promote
            target_space_id: Target team space ID
            team_principal_id: Team principal ID (new owner)
            name: Optional new name

        Returns:
            Created resource and promotion request info

        Raises:
            ResourceTypeError: If resource type doesn't allow promote
        """
        # Load source resource
        source = await session.get(Resource, source_id)
        if not source or source.tenant_id != actor.tenant_id:
            raise ValueError(f"Source resource {source_id} not found")

        # Validate action is allowed
        self._validate_action(source, GovernanceAction.PROMOTE)

        # Find or create staging subspace under target space
        staging_subspace = await self._get_or_create_staging_subspace(
            session, actor, target_space_id
        )

        # Copy artifact files if present
        new_artifact_ref = None
        if source.artifact_ref:
            new_artifact_ref = self._artifact_manager.copy_artifact(source.artifact_ref)

        # Create new resource in staging
        new_id = uuid4()
        new_resource = Resource(
            id=new_id,
            tenant_id=actor.tenant_id,
            type=source.type,
            parent_id=staging_subspace.id,
            owner_principal_id=team_principal_id,  # Team owns promoted resource
            space_kind="team",
            subspace_kind="staging",  # Promoted to staging first
            name=name or source.name,
            status="pending_approval",  # Pending until approved
            metadata_json=source.metadata_json.copy() if source.metadata_json else {},
            artifact_ref=new_artifact_ref,
        )
        session.add(new_resource)

        # Create lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=new_id,
            dst_resource_id=source_id,
            edge_type="promoted_from",
            created_by_principal_id=actor.id,
        )
        session.add(edge)

        # Flush to satisfy FK constraint before creating role bindings
        await session.flush()

        # RBAC mutations: team=owner, promoter=delegator
        team_owner_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=team_principal_id,
            scope_resource_id=new_id,
            role_name="owner",
            granted_by=actor.id,
        )
        session.add(team_owner_binding)

        promoter_binding = RoleBinding(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            principal_id=actor.id,
            scope_resource_id=new_id,
            role_name="delegator",
            granted_by=actor.id,
        )
        session.add(promoter_binding)

        # Find official subspace for promotion request
        official_subspace = await self._get_official_subspace(session, target_space_id)

        # Create promotion request
        pr_resource = Resource(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            type="PromotionRequest",
            parent_id=staging_subspace.id,
            owner_principal_id=actor.id,
            name=f"Promote {new_resource.name}",
            status="open",
        )
        session.add(pr_resource)

        # Flush pr_resource to satisfy FK before creating PromotionRequest
        await session.flush()

        promotion_request = PromotionRequest(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            pr_resource_id=pr_resource.id,
            moving_resource_id=new_id,
            from_scope_id=staging_subspace.id,
            to_scope_id=official_subspace.id
            if official_subspace
            else staging_subspace.id,
            mode="promote",
            status="open",
            required_approvals=1,
            created_by=actor.id,
        )
        session.add(promotion_request)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=new_id,
            resource_type=source.type,
            action="resource.promoted",
            payload={
                "source_id": str(source_id),
                "target_space_id": str(target_space_id),
                "staging_subspace_id": str(staging_subspace.id),
                "team_principal_id": str(team_principal_id),
                "name": new_resource.name,
                "artifact_ref": str(new_artifact_ref) if new_artifact_ref else None,
                "promotion_request_id": str(promotion_request.id),
                "status": "pending_approval",
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.resource_promoted_to_staging",
            source_id=str(source_id),
            target_id=str(new_id),
            team_id=str(team_principal_id),
            promotion_request_id=str(promotion_request.id),
            actor_id=str(actor.id),
        )

        return {
            "id": str(new_id),
            "name": new_resource.name,
            "type": new_resource.type,
            "source_id": str(source_id),
            "team_principal_id": str(team_principal_id),
            "artifact_ref": str(new_artifact_ref) if new_artifact_ref else None,
            "subspace_kind": "staging",
            "promotion_request_id": str(promotion_request.id),
            "status": "pending_approval",
            "operation": "promote",
        }

    async def approve_promotion(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        promotion_request_id: UUID,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Approve a promotion request, auto-moving resource to official.

        When all required approvals are met, the resource is:
        1. Moved from staging to official subspace
        2. Status updated to 'active'

        Args:
            session: Database session
            actor: Actor context (approver)
            promotion_request_id: Promotion request to approve
            comment: Optional approval comment

        Returns:
            Approval result info
        """
        # Load promotion request
        promotion_request = await session.get(PromotionRequest, promotion_request_id)
        if not promotion_request or promotion_request.tenant_id != actor.tenant_id:
            raise ValueError(f"Promotion request {promotion_request_id} not found")

        if promotion_request.status != "open":
            raise ValueError(
                f"Promotion request is {promotion_request.status}, not open"
            )

        # Check if actor already approved
        existing_approval = await session.execute(
            select(Approval).where(
                Approval.tenant_id == actor.tenant_id,
                Approval.resource_id == promotion_request.pr_resource_id,
                Approval.approver_id == actor.id,
            )
        )
        if existing_approval.scalar_one_or_none():
            raise ValueError("You have already submitted an approval for this request")

        # Create approval
        approval = Approval(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            resource_id=promotion_request.pr_resource_id,
            approver_id=actor.id,
            decision="approved",
            comment=comment,
        )
        session.add(approval)

        # Count approvals
        approvals_result = await session.execute(
            select(Approval).where(
                Approval.tenant_id == actor.tenant_id,
                Approval.resource_id == promotion_request.pr_resource_id,
                Approval.decision == "approved",
            )
        )
        approval_count = (
            len(list(approvals_result.scalars().all())) + 1
        )  # +1 for current

        result: dict[str, Any] = {
            "promotion_request_id": str(promotion_request_id),
            "approver_id": str(actor.id),
            "approval_count": approval_count,
            "required_approvals": promotion_request.required_approvals,
            "operation": "promotion_approved",
        }

        # Check if all required approvals are met
        if approval_count >= promotion_request.required_approvals:
            # Move resource to official
            resource = await session.get(Resource, promotion_request.moving_resource_id)
            if resource:
                resource.parent_id = promotion_request.to_scope_id
                resource.subspace_kind = "official"
                resource.status = "active"

                # Update promotion request status
                promotion_request.status = "merged"

                result["resource_id"] = str(resource.id)
                result["moved_to"] = "official"
                result["status"] = "merged"

                # Emit activity
                envelope = ActivityEnvelope(
                    tenant_id=actor.tenant_id,
                    actor_principal_id=actor.id,
                    resource_id=resource.id,
                    resource_type=resource.type,
                    action="promotion.completed",
                    payload={
                        "promotion_request_id": str(promotion_request_id),
                        "moved_to_official": True,
                        "approval_count": approval_count,
                    },
                )
                await record_activity_with_outbox(session, envelope)

                logger.info(
                    "governance.promotion_completed",
                    promotion_request_id=str(promotion_request_id),
                    resource_id=str(resource.id),
                    moved_to="official",
                )
        else:
            result["status"] = "pending"

        # Emit approval activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=promotion_request.pr_resource_id,
            resource_type="PromotionRequest",
            action="promotion.approved",
            payload={
                "promotion_request_id": str(promotion_request_id),
                "comment": comment,
                "approval_count": approval_count,
                "required_approvals": promotion_request.required_approvals,
            },
        )
        await record_activity_with_outbox(session, envelope)

        return result

    async def _get_or_create_staging_subspace(
        self,
        session: AsyncSession,
        actor: ActorContext,
        space_id: UUID,
    ) -> Resource:
        """Get or create a staging subspace under a space."""
        # Look for existing staging subspace
        result = await session.execute(
            select(Resource).where(
                Resource.tenant_id == actor.tenant_id,
                Resource.parent_id == space_id,
                Resource.type == "SubSpace",
                Resource.subspace_kind == "staging",
            )
        )
        staging = result.scalar_one_or_none()

        if staging:
            return staging

        # Create staging subspace
        space = await session.get(Resource, space_id)
        if not space:
            raise ValueError(f"Space {space_id} not found")

        staging = Resource(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            type="SubSpace",
            parent_id=space_id,
            owner_principal_id=space.owner_principal_id,
            space_kind=space.space_kind,
            subspace_kind="staging",
            name="Staging",
            status="active",
        )
        session.add(staging)
        return staging

    async def _get_official_subspace(
        self,
        session: AsyncSession,
        space_id: UUID,
    ) -> Resource | None:
        """Get the official subspace under a space."""
        result = await session.execute(
            select(Resource).where(
                Resource.parent_id == space_id,
                Resource.type == "SubSpace",
                Resource.subspace_kind == "official",
            )
        )
        return result.scalar_one_or_none()

    # =========================================================================
    # Merge Operations
    # =========================================================================

    async def merge_resource(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        source_id: UUID,
        target_id: UUID,
    ) -> dict[str, Any]:
        """Merge a branch back to its ancestor.

        Merge replaces the ancestor's artifact with the branch's artifact.
        The source (branch) is marked as merged.
        Contributor credit is tracked via lineage edge.

        Only allowed for Definition and Instance resources (not Projects, not Flows).

        Args:
            session: Database session
            actor: Actor context
            source_id: Branch resource ID (source of merge)
            target_id: Ancestor resource ID (target to update)

        Returns:
            Merge result info

        Raises:
            ResourceTypeError: If resource type doesn't allow merge
        """
        # Load resources
        source = await session.get(Resource, source_id)
        if not source or source.tenant_id != actor.tenant_id:
            raise ValueError(f"Source resource {source_id} not found")

        target = await session.get(Resource, target_id)
        if not target or target.tenant_id != actor.tenant_id:
            raise ValueError(f"Target resource {target_id} not found")

        # Validate action is allowed
        self._validate_action(source, GovernanceAction.MERGE)

        # Verify source is a branch of target
        branch_edge = await session.execute(
            select(ResourceEdge).where(
                ResourceEdge.tenant_id == actor.tenant_id,
                ResourceEdge.src_resource_id == source_id,
                ResourceEdge.dst_resource_id == target_id,
                ResourceEdge.edge_type == "branch_of",
            )
        )
        if not branch_edge.scalar_one_or_none():
            raise ValueError(f"Resource {source_id} is not a branch of {target_id}")

        # Store old artifact ref for cleanup
        old_artifact_ref = target.artifact_ref

        # Replace target artifact with source artifact
        target.artifact_ref = source.artifact_ref

        # Mark source as merged (status change)
        source.status = "merged"

        # Create merge lineage edge
        edge = ResourceEdge(
            tenant_id=actor.tenant_id,
            src_resource_id=target_id,
            dst_resource_id=source_id,
            edge_type="merged_from",
            created_by_principal_id=actor.id,
        )
        session.add(edge)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=target_id,
            resource_type=target.type,
            action="resource.merged",
            payload={
                "source_id": str(source_id),
                "target_id": str(target_id),
                "source_owner_id": str(source.owner_principal_id),
                "old_artifact_ref": str(old_artifact_ref) if old_artifact_ref else None,
                "new_artifact_ref": str(source.artifact_ref)
                if source.artifact_ref
                else None,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "governance.resource_merged",
            source_id=str(source_id),
            target_id=str(target_id),
            contributor_id=str(source.owner_principal_id),
            actor_id=str(actor.id),
        )

        return {
            "target_id": str(target_id),
            "source_id": str(source_id),
            "contributor_id": str(source.owner_principal_id),
            "artifact_ref": str(target.artifact_ref) if target.artifact_ref else None,
            "operation": "merge",
        }

    # =========================================================================
    # Lineage Queries
    # =========================================================================

    async def get_resource_lineage(
        self,
        session: AsyncSession,
        actor: ActorContext,
        resource_id: UUID,
        *,
        direction: str = "upstream",
        edge_types: list[str] | None = None,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        """Get resource lineage (ancestors or descendants).

        Args:
            session: Database session
            actor: Actor context
            resource_id: Starting resource
            direction: "upstream" (ancestors) or "downstream" (descendants)
            edge_types: Filter by edge types (e.g., ["branch_of", "promoted_from"])
            max_depth: Maximum traversal depth

        Returns:
            List of lineage entries with resource info and edge type
        """
        lineage: list[dict[str, Any]] = []
        visited: set[UUID] = set()
        to_visit: list[tuple[UUID, int]] = [(resource_id, 0)]

        while to_visit:
            current_id, depth = to_visit.pop(0)

            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)

            # Skip the starting resource in results
            if current_id != resource_id:
                resource = await session.get(Resource, current_id)
                if resource and resource.tenant_id == actor.tenant_id:
                    lineage.append(
                        {
                            "id": str(resource.id),
                            "name": resource.name,
                            "type": resource.type,
                            "depth": depth,
                        }
                    )

            # Find edges
            if direction == "upstream":
                # Find where current is source, get destinations
                query = select(ResourceEdge).where(
                    ResourceEdge.tenant_id == actor.tenant_id,
                    ResourceEdge.src_resource_id == current_id,
                )
            else:
                # Find where current is destination, get sources
                query = select(ResourceEdge).where(
                    ResourceEdge.tenant_id == actor.tenant_id,
                    ResourceEdge.dst_resource_id == current_id,
                )

            if edge_types:
                query = query.where(ResourceEdge.edge_type.in_(edge_types))

            result = await session.execute(query)
            for edge in result.scalars().all():
                next_id = (
                    edge.dst_resource_id
                    if direction == "upstream"
                    else edge.src_resource_id
                )
                if next_id not in visited:
                    to_visit.append((next_id, depth + 1))

        return lineage

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_pending_transfer_requests(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        as_sender: bool = False,
        as_recipient: bool = True,
    ) -> list[TransferRequest]:
        """Get pending transfer requests for the actor.

        Args:
            session: Database session
            actor: Actor context
            as_sender: Include requests where actor is sender
            as_recipient: Include requests where actor is recipient

        Returns:
            List of pending transfer requests
        """
        conditions = [
            TransferRequest.tenant_id == actor.tenant_id,
            TransferRequest.status == "pending",
        ]

        if as_sender and as_recipient:
            from sqlalchemy import or_

            conditions.append(
                or_(
                    TransferRequest.sender_id == actor.id,
                    TransferRequest.recipient_id == actor.id,
                )
            )
        elif as_sender:
            conditions.append(TransferRequest.sender_id == actor.id)
        elif as_recipient:
            conditions.append(TransferRequest.recipient_id == actor.id)
        else:
            return []

        result = await session.execute(select(TransferRequest).where(*conditions))
        return list(result.scalars().all())

    async def get_pending_promotions(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        space_id: UUID | None = None,
    ) -> list[PromotionRequest]:
        """Get pending promotion requests.

        Args:
            session: Database session
            actor: Actor context
            space_id: Optional space to filter by

        Returns:
            List of pending promotion requests
        """
        conditions = [
            PromotionRequest.tenant_id == actor.tenant_id,
            PromotionRequest.status == "open",
        ]

        if space_id:
            conditions.append(PromotionRequest.to_scope_id == space_id)

        result = await session.execute(select(PromotionRequest).where(*conditions))
        return list(result.scalars().all())
