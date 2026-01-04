"""
API test fixtures - Multi-account sandbox infrastructure.

Provides comprehensive fixtures for testing:
- Multi-tenant isolation (multiple tenants with separate users)
- RBAC with different role bindings (admin, analyst, viewer, no-access)
- Resource hierarchies (Space -> Project -> DatasetInstance)
- Activity/Audit logging verification
- Lineage relationships

All fixtures use real database sessions from the sandbox infrastructure.
NO MOCKS - tests verify actual database operations and business logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.activity import Activity
from libs.db.models.identity import Principal, Tenant
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.db.models.resource import Resource


def utcnow() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


# =============================================================================
# DATA CLASSES FOR MULTI-ACCOUNT SANDBOX
# =============================================================================


@dataclass
class SandboxUser:
    """Represents a user in the sandbox."""

    id: UUID
    tenant_id: UUID
    display_name: str
    email: str
    role: str  # admin, analyst, viewer

    def to_actor(self) -> ActorContext:
        """Create an ActorContext for this user."""
        return ActorContext(
            id=self.id,
            tenant_id=self.tenant_id,
            traits={"role": self.role},
            kind="user",
        )


@dataclass
class SandboxTenant:
    """Represents a tenant organization in the sandbox."""

    id: UUID
    name: str
    admin: SandboxUser
    analysts: list[SandboxUser] = field(default_factory=list)
    viewers: list[SandboxUser] = field(default_factory=list)
    spaces: list[UUID] = field(default_factory=list)

    @property
    def all_users(self) -> list[SandboxUser]:
        """Get all users in this tenant."""
        return [self.admin] + self.analysts + self.viewers


@dataclass
class SandboxEnvironment:
    """Complete multi-tenant sandbox environment."""

    tenant_alpha: SandboxTenant
    tenant_beta: SandboxTenant
    external_user: SandboxUser  # User with no access to either tenant


# =============================================================================
# SANDBOX CREATION HELPERS - Using ORM models for proper UUID handling
# =============================================================================


async def create_tenant_orm(
    db_session: AsyncSession,
    name: str,
) -> Tenant:
    """Create a tenant using ORM and return the model."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name=name,
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def create_principal_orm(
    db_session: AsyncSession,
    tenant_id: UUID,
    display_name: str,
    email: str,
    kind: str = "user",
) -> Principal:
    """Create a principal using ORM and return the model."""
    principal = Principal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        kind=kind,
        status="active",
        display_name=display_name,
        email=email,
    )
    db_session.add(principal)
    await db_session.flush()
    return principal


async def create_resource(
    db_session: AsyncSession,
    tenant_id: UUID,
    owner_principal_id: UUID,
    resource_type: str,
    name: str,
    parent_id: Optional[UUID] = None,
    space_kind: Optional[str] = None,
    subspace_kind: Optional[str] = None,
) -> UUID:
    """Create a resource using ORM and return its ID."""
    resource = Resource(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        owner_principal_id=owner_principal_id,
        type=resource_type,
        name=name,
        parent_id=parent_id,
        space_kind=space_kind,
        subspace_kind=subspace_kind,
        status="active",
    )
    db_session.add(resource)
    await db_session.flush()
    return resource.id


async def create_role_binding(
    db_session: AsyncSession,
    tenant_id: UUID,
    principal_id: UUID,
    scope_resource_id: UUID,
    role_name: str,
    granted_by: UUID,
) -> UUID:
    """Create a role binding using ORM and return its ID."""
    binding = RoleBinding(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        principal_id=principal_id,
        scope_resource_id=scope_resource_id,
        role_name=role_name,
        granted_by=granted_by,
    )
    db_session.add(binding)
    await db_session.flush()
    return binding.id


async def create_role_permission(
    db_session: AsyncSession,
    tenant_id: UUID,
    resource_type: str,
    role_name: str,
    perm_name: str,
) -> None:
    """Create a role permission mapping using ORM."""
    perm = RolePermission(
        tenant_id=tenant_id,
        resource_type=resource_type,
        role_name=role_name,
        perm_name=perm_name,
    )
    db_session.add(perm)
    await db_session.flush()


async def setup_default_role_permissions(
    db_session: AsyncSession,
    tenant_id: UUID,
) -> None:
    """Set up default role permissions for a tenant."""
    # Admin role - all permissions
    admin_perms = [
        Permission.RESOURCE_READ,
        Permission.RESOURCE_CREATE_CHILD,
        Permission.RESOURCE_UPDATE,
        Permission.RESOURCE_DELETE,
        Permission.RBAC_GRANT,
        Permission.RBAC_REVOKE,
        Permission.RBAC_VIEW,
        Permission.VIEW_ACTIVITY_FEED,
    ]
    for perm in admin_perms:
        await create_role_permission(db_session, tenant_id, "*", "admin", perm.value)

    # Analyst role - read/write but no RBAC
    analyst_perms = [
        Permission.RESOURCE_READ,
        Permission.RESOURCE_CREATE_CHILD,
        Permission.RESOURCE_UPDATE,
        Permission.VIEW_ACTIVITY_FEED,
    ]
    for perm in analyst_perms:
        await create_role_permission(db_session, tenant_id, "*", "analyst", perm.value)

    # Viewer role - read only
    viewer_perms = [
        Permission.RESOURCE_READ,
        Permission.VIEW_ACTIVITY_FEED,
    ]
    for perm in viewer_perms:
        await create_role_permission(db_session, tenant_id, "*", "viewer", perm.value)


async def create_sandbox_tenant(
    db_session: AsyncSession,
    name: str,
    num_analysts: int = 2,
    num_viewers: int = 1,
) -> SandboxTenant:
    """Create a complete tenant with admin, analysts, and viewers."""
    # Create tenant using ORM
    tenant = await create_tenant_orm(db_session, name)
    tenant_id = tenant.id

    # Set up default role permissions
    await setup_default_role_permissions(db_session, tenant_id)

    # Create admin user using ORM
    admin_principal = await create_principal_orm(
        db_session, tenant_id, f"{name} Admin", f"admin@{name.lower()}.com"
    )
    admin = SandboxUser(
        id=admin_principal.id,
        tenant_id=tenant_id,
        display_name=f"{name} Admin",
        email=f"admin@{name.lower()}.com",
        role="admin",
    )

    # Create a root space for this tenant
    space_id = await create_resource(
        db_session,
        tenant_id,
        admin.id,
        "Space",
        f"{name} Team Space",
        space_kind="team",
    )

    # Grant admin role on root space
    await create_role_binding(
        db_session, tenant_id, admin.id, space_id, "admin", admin.id
    )

    # Create analyst users
    analysts = []
    for i in range(num_analysts):
        analyst_principal = await create_principal_orm(
            db_session,
            tenant_id,
            f"{name} Analyst {i + 1}",
            f"analyst{i + 1}@{name.lower()}.com",
        )
        analyst = SandboxUser(
            id=analyst_principal.id,
            tenant_id=tenant_id,
            display_name=f"{name} Analyst {i + 1}",
            email=f"analyst{i + 1}@{name.lower()}.com",
            role="analyst",
        )
        analysts.append(analyst)
        # Grant analyst role on space
        await create_role_binding(
            db_session, tenant_id, analyst.id, space_id, "analyst", admin.id
        )

    # Create viewer users
    viewers = []
    for i in range(num_viewers):
        viewer_principal = await create_principal_orm(
            db_session,
            tenant_id,
            f"{name} Viewer {i + 1}",
            f"viewer{i + 1}@{name.lower()}.com",
        )
        viewer = SandboxUser(
            id=viewer_principal.id,
            tenant_id=tenant_id,
            display_name=f"{name} Viewer {i + 1}",
            email=f"viewer{i + 1}@{name.lower()}.com",
            role="viewer",
        )
        viewers.append(viewer)
        # Grant viewer role on space
        await create_role_binding(
            db_session, tenant_id, viewer.id, space_id, "viewer", admin.id
        )

    return SandboxTenant(
        id=tenant_id,
        name=name,
        admin=admin,
        analysts=analysts,
        viewers=viewers,
        spaces=[space_id],
    )


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def sandbox_env(db_session: AsyncSession) -> SandboxEnvironment:
    """Create a complete multi-tenant sandbox environment.

    Creates two tenants (Alpha and Beta) each with:
    - 1 admin user
    - 2 analyst users
    - 1 viewer user
    - 1 root team space with RBAC bindings

    Also creates an external user with no access to either tenant.
    """
    # Create Tenant Alpha
    tenant_alpha = await create_sandbox_tenant(db_session, "Alpha")

    # Create Tenant Beta
    tenant_beta = await create_sandbox_tenant(db_session, "Beta")

    # Create external user (belongs to a third tenant with no resources)
    external_tenant = await create_tenant_orm(db_session, "External")
    external_principal = await create_principal_orm(
        db_session, external_tenant.id, "External User", "external@other.com"
    )
    external_user = SandboxUser(
        id=external_principal.id,
        tenant_id=external_tenant.id,
        display_name="External User",
        email="external@other.com",
        role="none",
    )

    return SandboxEnvironment(
        tenant_alpha=tenant_alpha,
        tenant_beta=tenant_beta,
        external_user=external_user,
    )


@pytest_asyncio.fixture(scope="function")
async def sandbox_with_resources(
    db_session: AsyncSession,
    sandbox_env: SandboxEnvironment,
) -> SandboxEnvironment:
    """Sandbox environment with additional resources for testing.

    Extends sandbox_env with:
    - Projects under each tenant's space
    - DatasetInstances under projects
    - Resource hierarchy for RBAC inheritance testing
    """
    for tenant in [sandbox_env.tenant_alpha, sandbox_env.tenant_beta]:
        space_id = tenant.spaces[0]

        # Create projects
        for i in range(2):
            project_id = await create_resource(
                db_session,
                tenant.id,
                tenant.admin.id,
                "Project",
                f"{tenant.name} Project {i + 1}",
                parent_id=space_id,
            )

            # Create datasets under project
            for j in range(2):
                await create_resource(
                    db_session,
                    tenant.id,
                    tenant.admin.id,
                    "DatasetInstance",
                    f"Dataset {i + 1}.{j + 1}",
                    parent_id=project_id,
                )

    return sandbox_env


@pytest_asyncio.fixture(scope="function")
async def alpha_admin_actor(sandbox_env: SandboxEnvironment) -> ActorContext:
    """ActorContext for Tenant Alpha's admin."""
    return sandbox_env.tenant_alpha.admin.to_actor()


@pytest_asyncio.fixture(scope="function")
async def alpha_analyst_actor(sandbox_env: SandboxEnvironment) -> ActorContext:
    """ActorContext for Tenant Alpha's first analyst."""
    return sandbox_env.tenant_alpha.analysts[0].to_actor()


@pytest_asyncio.fixture(scope="function")
async def alpha_viewer_actor(sandbox_env: SandboxEnvironment) -> ActorContext:
    """ActorContext for Tenant Alpha's first viewer."""
    return sandbox_env.tenant_alpha.viewers[0].to_actor()


@pytest_asyncio.fixture(scope="function")
async def beta_admin_actor(sandbox_env: SandboxEnvironment) -> ActorContext:
    """ActorContext for Tenant Beta's admin."""
    return sandbox_env.tenant_beta.admin.to_actor()


@pytest_asyncio.fixture(scope="function")
async def external_actor(sandbox_env: SandboxEnvironment) -> ActorContext:
    """ActorContext for external user with no tenant access."""
    return sandbox_env.external_user.to_actor()


# =============================================================================
# ACTIVITY/AUDIT HELPERS
# =============================================================================


async def create_activity(
    db_session: AsyncSession,
    tenant_id: UUID,
    actor_principal_id: UUID,
    resource_id: UUID,
    resource_type: str,
    action: str,
    payload: Optional[dict] = None,
    visibility: str = "resource",
) -> UUID:
    """Create an activity record using ORM and return its ID."""
    activity = Activity(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_principal_id=actor_principal_id,
        resource_id=resource_id,
        resource_type=resource_type,
        action=action,
        visibility=visibility,
        payload=payload or {},
    )
    db_session.add(activity)
    await db_session.flush()
    return activity.id


async def get_activities_for_tenant(
    db_session: AsyncSession,
    tenant_id: UUID,
) -> list[dict]:
    """Get all activities for a tenant."""
    stmt = (
        select(Activity)
        .where(Activity.tenant_id == tenant_id)
        .order_by(Activity.created_at.desc())
    )
    result = await db_session.execute(stmt)
    activities = result.scalars().all()
    return [
        {
            "id": a.id,
            "tenant_id": a.tenant_id,
            "actor_principal_id": a.actor_principal_id,
            "resource_id": a.resource_id,
            "resource_type": a.resource_type,
            "action": a.action,
            "created_at": a.created_at,
        }
        for a in activities
    ]


# =============================================================================
# LINEAGE HELPERS
# =============================================================================


async def create_lineage_edge(
    db_session: AsyncSession,
    tenant_id: UUID,
    upstream_id: UUID,
    downstream_id: UUID,
    edge_kind: str = "data_dependency",
) -> None:
    """Create a lineage edge between resources using ORM."""
    from libs.db.models.quant import DatasetLineage

    edge = DatasetLineage(
        tenant_id=tenant_id,
        upstream_resource_id=upstream_id,
        downstream_resource_id=downstream_id,
        edge_kind=edge_kind,
    )
    db_session.add(edge)
    await db_session.flush()


async def get_lineage_edges(
    db_session: AsyncSession,
    tenant_id: UUID,
) -> list[dict]:
    """Get all lineage edges for a tenant."""
    from libs.db.models.quant import DatasetLineage

    stmt = select(DatasetLineage).where(DatasetLineage.tenant_id == tenant_id)
    result = await db_session.execute(stmt)
    edges = result.scalars().all()
    return [
        {
            "upstream_id": e.upstream_resource_id,
            "downstream_id": e.downstream_resource_id,
            "edge_kind": e.edge_kind,
        }
        for e in edges
    ]


# =============================================================================
# PRINCIPAL CREATION HELPER (for use in tests)
# =============================================================================


async def create_principal(
    db_session: AsyncSession,
    tenant_id: UUID,
    display_name: str,
    email: str,
    kind: str = "user",
) -> UUID:
    """Create a principal and return its ID."""
    principal = await create_principal_orm(
        db_session, tenant_id, display_name, email, kind
    )
    return principal.id
