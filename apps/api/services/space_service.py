"""Space Service - Space and User Management.

Handles:
- Space creation with automatic Official + Staging sub-spaces
- User creation with Personal Space
- Team Space creation with owner assignment
- RBAC grants for space visibility

Follows the space hierarchy pattern:
- Space (space_kind: personal|team|system)
  - Subspace (subspace_kind: official|staging|custom)
    - Project
      - Resources
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import (
    ActivityEnvelope,
    record_activity_with_outbox,
    tx_activity,
)
from libs.core.rbac.models import ActorContext
from libs.db.models.identity import Principal
from libs.db.models.rbac import RoleBinding
from libs.db.models.resource import Resource

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SpaceCreationResult:
    """Result of space creation with sub-spaces."""

    space_id: UUID
    official_subspace_id: UUID
    staging_subspace_id: UUID


@dataclass(frozen=True)
class UserCreationResult:
    """Result of user creation with Personal Space."""

    principal_id: UUID
    personal_space: SpaceCreationResult


class SpaceService:
    """Service for Space and User management.

    Spaces are organized hierarchically:
    - TenantRoot
      - Space (personal|team|system)
        - Subspace (official|staging)
          - Project
            - Resources

    Each user has a Personal Space with Official and Staging sub-spaces.
    Teams have Team Spaces owned by designated principals.
    The System Space contains built-in definitions visible to all users.
    """

    async def create_space_with_subspaces(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        parent_id: UUID,
        space_kind: str,  # "personal" | "team" | "system"
        owner_principal_id: UUID,
        description: str | None = None,
    ) -> SpaceCreationResult:
        """Create a Space with default Official and Staging sub-spaces.

        This is the core pattern for space creation:
        1. Create Space resource
        2. Create Official subspace
        3. Create Staging subspace
        4. Grant owner role to owner_principal_id
        5. Emit activities

        Args:
            session: Database session
            actor: Actor context for activity attribution
            name: Space name
            parent_id: Parent resource ID (usually TenantRoot)
            space_kind: Type of space (personal, team, system)
            owner_principal_id: Principal who will own this space
            description: Optional description

        Returns:
            SpaceCreationResult with all created IDs
        """
        space_id = uuid4()
        official_id = uuid4()
        staging_id = uuid4()

        # Create Space
        async def create_space_fn(sess: AsyncSession) -> Resource:
            space = Resource(
                id=space_id,
                tenant_id=actor.tenant_id,
                type="Space",
                parent_id=parent_id,
                owner_principal_id=owner_principal_id,
                name=name,
                status="active",
                space_kind=space_kind,
                subspace_kind=None,  # Space itself, not a subspace
                metadata_json={"description": description or f"{name} space"},
            )
            sess.add(space)
            await sess.flush()
            return space

        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=space_id,
            resource_type="Space",
            action="space.created",
            payload={
                "name": name,
                "space_kind": space_kind,
                "owner_principal_id": str(owner_principal_id),
            },
        )
        await tx_activity(session, envelope, create_space_fn)

        # Create Official Subspace
        await self._create_subspace(
            session,
            actor,
            parent_space_id=space_id,
            subspace_id=official_id,
            name=f"{name} Official",
            subspace_kind="official",
            space_kind=space_kind,
            owner_principal_id=owner_principal_id,
        )

        # Create Staging Subspace
        await self._create_subspace(
            session,
            actor,
            parent_space_id=space_id,
            subspace_id=staging_id,
            name=f"{name} Staging",
            subspace_kind="staging",
            space_kind=space_kind,
            owner_principal_id=owner_principal_id,
        )

        # Grant owner role on Space
        binding = RoleBinding(
            tenant_id=actor.tenant_id,
            principal_id=owner_principal_id,
            scope_resource_id=space_id,
            role_name="owner",
            granted_by=actor.id,
        )
        session.add(binding)

        # Emit RBAC grant activity
        rbac_envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=space_id,
            resource_type="Space",
            action="rbac.granted",
            payload={
                "principal_id": str(owner_principal_id),
                "role": "owner",
                "scope_resource_id": str(space_id),
            },
        )
        await record_activity_with_outbox(session, rbac_envelope)

        await session.flush()

        logger.info(
            "space.created_with_subspaces",
            space_id=str(space_id),
            space_kind=space_kind,
            owner=str(owner_principal_id),
        )

        return SpaceCreationResult(
            space_id=space_id,
            official_subspace_id=official_id,
            staging_subspace_id=staging_id,
        )

    async def _create_subspace(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        parent_space_id: UUID,
        subspace_id: UUID,
        name: str,
        subspace_kind: str,
        space_kind: str,
        owner_principal_id: UUID,
    ) -> None:
        """Create a subspace under a space."""

        async def create_subspace_fn(sess: AsyncSession) -> Resource:
            subspace = Resource(
                id=subspace_id,
                tenant_id=actor.tenant_id,
                type="Subspace",
                parent_id=parent_space_id,
                owner_principal_id=owner_principal_id,
                name=name,
                status="active",
                space_kind=space_kind,
                subspace_kind=subspace_kind,
                metadata_json={},
            )
            sess.add(subspace)
            await sess.flush()
            return subspace

        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=subspace_id,
            resource_type="Subspace",
            action="subspace.created",
            payload={
                "name": name,
                "subspace_kind": subspace_kind,
                "parent_space_id": str(parent_space_id),
            },
        )
        await tx_activity(session, envelope, create_subspace_fn)

    async def create_user_with_personal_space(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        display_name: str,
        email: str | None = None,
        tenant_root_id: UUID,
    ) -> UserCreationResult:
        """Create a user with their Personal Space.

        This is the user creation pattern:
        1. Create Principal
        2. Create Personal Space with Official + Staging sub-spaces
        3. Grant owner role on Personal Space
        4. Optionally grant view access to System Space

        Args:
            session: Database session
            actor: Actor context (must have INVITE_CREATE permission)
            display_name: User's display name
            email: User's email
            tenant_root_id: TenantRoot resource ID for space parent

        Returns:
            UserCreationResult with principal and space IDs
        """
        principal_id = uuid4()

        # Create Principal
        async def create_principal_fn(sess: AsyncSession) -> Principal:
            principal = Principal(
                id=principal_id,
                tenant_id=actor.tenant_id,
                kind="user",
                status="active",
                display_name=display_name,
                email=email,
            )
            sess.add(principal)
            await sess.flush()
            return principal

        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=tenant_root_id,  # Activity on tenant root
            resource_type="TenantRoot",
            action="user.created",
            target_principal_id=principal_id,
            payload={
                "principal_id": str(principal_id),
                "display_name": display_name,
            },
        )
        await tx_activity(session, envelope, create_principal_fn)

        # Create Personal Space
        space_result = await self.create_space_with_subspaces(
            session,
            actor,
            name=f"{display_name}'s Space",
            parent_id=tenant_root_id,
            space_kind="personal",
            owner_principal_id=principal_id,
            description=f"Personal space for {display_name}",
        )

        logger.info(
            "user.created_with_personal_space",
            principal_id=str(principal_id),
            space_id=str(space_result.space_id),
        )

        return UserCreationResult(
            principal_id=principal_id,
            personal_space=space_result,
        )

    async def create_team_space(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        owner_principal_id: UUID,
        tenant_root_id: UUID,
        member_principal_ids: list[UUID] | None = None,
        description: str | None = None,
    ) -> SpaceCreationResult:
        """Create a Team Space with an assigned owner.

        Args:
            session: Database session
            actor: Actor context (must be admin)
            name: Team name
            owner_principal_id: Principal who will own this team space
            tenant_root_id: TenantRoot resource ID for space parent
            member_principal_ids: Optional list of members to add as operators
            description: Optional description

        Returns:
            SpaceCreationResult with all created IDs
        """
        # Create Team Space
        space_result = await self.create_space_with_subspaces(
            session,
            actor,
            name=name,
            parent_id=tenant_root_id,
            space_kind="team",
            owner_principal_id=owner_principal_id,
            description=description or f"Team space: {name}",
        )

        # Grant operator role to members
        if member_principal_ids:
            for member_id in member_principal_ids:
                if member_id == owner_principal_id:
                    continue  # Owner already has owner role

                binding = RoleBinding(
                    tenant_id=actor.tenant_id,
                    principal_id=member_id,
                    scope_resource_id=space_result.space_id,
                    role_name="operator",
                    granted_by=actor.id,
                )
                session.add(binding)

                rbac_envelope = ActivityEnvelope(
                    tenant_id=actor.tenant_id,
                    actor_principal_id=actor.id,
                    resource_id=space_result.space_id,
                    resource_type="Space",
                    action="rbac.granted",
                    payload={
                        "principal_id": str(member_id),
                        "role": "operator",
                        "scope_resource_id": str(space_result.space_id),
                    },
                )
                await record_activity_with_outbox(session, rbac_envelope)

        await session.flush()

        logger.info(
            "team_space.created",
            space_id=str(space_result.space_id),
            owner=str(owner_principal_id),
            members_count=len(member_principal_ids or []),
        )

        return space_result

    async def grant_system_space_view_access(
        self,
        session: AsyncSession,
        actor: ActorContext,
        principal_id: UUID,
        system_space_id: UUID,
    ) -> bool:
        """Grant VIEW access to System Space for a user.

        All users should get viewer access to System Space to see
        system-provided definitions.

        Args:
            session: Database session
            actor: Actor context
            principal_id: Principal to grant access
            system_space_id: System Space ID

        Returns:
            True if granted, False if already exists
        """
        # Check if binding already exists
        existing = await session.scalars(
            select(RoleBinding).where(
                RoleBinding.tenant_id == actor.tenant_id,
                RoleBinding.principal_id == principal_id,
                RoleBinding.scope_resource_id == system_space_id,
                RoleBinding.revoked_at.is_(None),
            )
        )
        if existing.first():
            return False  # Already has access

        binding = RoleBinding(
            tenant_id=actor.tenant_id,
            principal_id=principal_id,
            scope_resource_id=system_space_id,
            role_name="viewer",
            granted_by=actor.id,
        )
        session.add(binding)

        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=system_space_id,
            resource_type="Space",
            action="rbac.granted",
            payload={
                "principal_id": str(principal_id),
                "role": "viewer",
                "scope_resource_id": str(system_space_id),
                "reason": "default_system_space_access",
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.flush()

        return True

    async def create_custom_subspace(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        parent_space_id: UUID,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a custom subspace under a space.

        Users can create additional subspaces beyond Official and Staging.

        Args:
            session: Database session
            actor: Actor context
            name: Subspace name
            parent_space_id: Parent Space ID
            description: Optional description

        Returns:
            Subspace info
        """
        # Get parent space to inherit space_kind
        parent = await session.get(Resource, parent_space_id)
        if not parent or parent.type != "Space":
            raise ValueError(f"Parent space {parent_space_id} not found")

        if parent.tenant_id != actor.tenant_id:
            raise ValueError("Cannot create subspace in another tenant's space")

        subspace_id = uuid4()

        async def create_fn(sess: AsyncSession) -> Resource:
            subspace = Resource(
                id=subspace_id,
                tenant_id=actor.tenant_id,
                type="Subspace",
                parent_id=parent_space_id,
                owner_principal_id=actor.id,
                name=name,
                status="active",
                space_kind=parent.space_kind,
                subspace_kind="custom",
                metadata_json={"description": description or name},
            )
            sess.add(subspace)
            await sess.flush()
            return subspace

        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=subspace_id,
            resource_type="Subspace",
            action="subspace.created",
            payload={
                "name": name,
                "subspace_kind": "custom",
                "parent_space_id": str(parent_space_id),
            },
        )
        await tx_activity(session, envelope, create_fn)

        return {
            "id": str(subspace_id),
            "name": name,
            "subspace_kind": "custom",
            "parent_space_id": str(parent_space_id),
        }
