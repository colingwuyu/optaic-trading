"""System Bootstrap Service.

Handles idempotent initialization of:
- System tenant with admin principal
- System Space with Official + Staging sub-spaces
- System Project containing all plugin definitions
- Default RBAC grants for System Space visibility

This module is called on application startup to ensure the system
is properly initialized. All operations are idempotent - safe to
call multiple times.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import Permission, GLOBAL_RESOURCE_TYPE
from libs.db.models.identity import Tenant, Principal
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.db.models.resource import Resource

logger = structlog.get_logger(__name__)

# =============================================================================
# Well-known System IDs
# =============================================================================
# These UUIDs are deterministic and used across the system to reference
# system-level entities. They follow the pattern 00000000-0000-0000-0000-XXXX

SYSTEM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_SPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
SYSTEM_PRINCIPAL_ID = UUID("00000000-0000-0000-0000-000000000003")
SYSTEM_TENANT_ROOT_ID = UUID("00000000-0000-0000-0000-000000000010")
SYSTEM_OFFICIAL_SUBSPACE_ID = UUID("00000000-0000-0000-0000-000000000011")
SYSTEM_STAGING_SUBSPACE_ID = UUID("00000000-0000-0000-0000-000000000012")
SYSTEM_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000013")


@dataclass(frozen=True)
class BootstrapResult:
    """Result of bootstrap operation."""

    tenant_id: UUID
    admin_principal_id: UUID
    system_space_id: UUID
    official_subspace_id: UUID
    staging_subspace_id: UUID
    project_id: UUID
    created: bool  # True if newly created, False if already existed


# =============================================================================
# Default Role Permissions
# =============================================================================
# These define what each role can do. Applied to GLOBAL_RESOURCE_TYPE ("*")
# so they apply to all resource types.

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "owner": [perm.value for perm in Permission],
    "operator": [
        Permission.RESOURCE_READ.value,
        Permission.RESOURCE_CREATE_CHILD.value,
        Permission.RESOURCE_UPDATE.value,
        Permission.VIEW_ACTIVITY_FEED.value,
        Permission.CHANNEL_VIEW_HISTORY.value,
        Permission.CHANNEL_POST.value,
        Permission.CHANNEL_EDIT_OWN.value,
        Permission.CHANNEL_DELETE_OWN.value,
        Permission.BRANCH_CREATE.value,
        Permission.MERGE_REQUEST_CREATE.value,
        Permission.SUBSCRIBE_RESOURCE.value,
        Permission.SUBSCRIBE_DESCENDANTS.value,
    ],
    "viewer": [
        Permission.RESOURCE_READ.value,
        Permission.VIEW_ACTIVITY_FEED.value,
        Permission.CHANNEL_VIEW_HISTORY.value,
        Permission.SUBSCRIBE_RESOURCE.value,
    ],
    "auditor": [
        Permission.VIEW_ACTIVITY_FEED.value,
        Permission.RBAC_VIEW.value,
    ],
}


# =============================================================================
# Bootstrap Functions
# =============================================================================


async def bootstrap_system(session: AsyncSession) -> BootstrapResult:
    """Bootstrap the system with tenant, admin, and System Space.

    This operation is idempotent - safe to call multiple times.

    Creates:
    1. System Tenant
    2. Admin Principal
    3. TenantRoot Resource
    4. Default role permissions (owner, operator, viewer, auditor)
    5. System Space with Official + Staging sub-spaces
    6. System Project for definitions
    7. Admin owner role on System Space

    Args:
        session: Database session

    Returns:
        BootstrapResult with all created IDs
    """
    # Check if already bootstrapped
    existing = await _get_system_tenant(session)
    if existing:
        logger.info("bootstrap.already_exists", tenant_id=str(SYSTEM_TENANT_ID))
        return BootstrapResult(
            tenant_id=SYSTEM_TENANT_ID,
            admin_principal_id=SYSTEM_PRINCIPAL_ID,
            system_space_id=SYSTEM_SPACE_ID,
            official_subspace_id=SYSTEM_OFFICIAL_SUBSPACE_ID,
            staging_subspace_id=SYSTEM_STAGING_SUBSPACE_ID,
            project_id=SYSTEM_PROJECT_ID,
            created=False,
        )

    logger.info("bootstrap.starting")

    # 1. Create System Tenant
    await _create_system_tenant(session)

    # 2. Create Admin Principal
    await _create_admin_principal(session)

    # 3. Create TenantRoot Resource
    await _create_tenant_root(session)

    # 4. Set up default role permissions
    await _setup_default_role_permissions(session)

    # 5. Create System Space with sub-spaces
    await _create_system_space_hierarchy(session)

    # 6. Create System Project
    await _create_system_project(session)

    # 7. Grant admin owner role on System Space
    await _grant_admin_owner_role(session)

    # Note: Caller is responsible for committing
    # In startup hooks, we commit after all operations complete
    await session.flush()

    logger.info(
        "bootstrap.completed",
        tenant_id=str(SYSTEM_TENANT_ID),
        admin_id=str(SYSTEM_PRINCIPAL_ID),
        space_id=str(SYSTEM_SPACE_ID),
        project_id=str(SYSTEM_PROJECT_ID),
    )

    return BootstrapResult(
        tenant_id=SYSTEM_TENANT_ID,
        admin_principal_id=SYSTEM_PRINCIPAL_ID,
        system_space_id=SYSTEM_SPACE_ID,
        official_subspace_id=SYSTEM_OFFICIAL_SUBSPACE_ID,
        staging_subspace_id=SYSTEM_STAGING_SUBSPACE_ID,
        project_id=SYSTEM_PROJECT_ID,
        created=True,
    )


async def _get_system_tenant(session: AsyncSession) -> Optional[Tenant]:
    """Check if system tenant exists."""
    result = await session.scalars(select(Tenant).where(Tenant.id == SYSTEM_TENANT_ID))
    return result.first()


async def _create_system_tenant(session: AsyncSession) -> None:
    """Create the system tenant."""
    tenant = Tenant(
        id=SYSTEM_TENANT_ID,
        name="OptAIC System",
    )
    session.add(tenant)
    await session.flush()
    logger.debug("bootstrap.tenant_created", tenant_id=str(SYSTEM_TENANT_ID))


async def _create_admin_principal(session: AsyncSession) -> None:
    """Create the system admin principal."""
    admin = Principal(
        id=SYSTEM_PRINCIPAL_ID,
        tenant_id=SYSTEM_TENANT_ID,
        kind="user",
        status="active",
        display_name="System Administrator",
        email="admin@optaic.local",
    )
    session.add(admin)
    await session.flush()
    logger.debug("bootstrap.admin_created", admin_id=str(SYSTEM_PRINCIPAL_ID))


async def _create_tenant_root(session: AsyncSession) -> None:
    """Create the TenantRoot resource."""
    root = Resource(
        id=SYSTEM_TENANT_ROOT_ID,
        tenant_id=SYSTEM_TENANT_ID,
        type="TenantRoot",
        parent_id=None,
        owner_principal_id=SYSTEM_PRINCIPAL_ID,
        name="OptAIC System Root",
        status="active",
        space_kind="system",
        subspace_kind=None,  # Root is not a subspace
        metadata_json={"root": True, "system": True},
    )
    session.add(root)
    await session.flush()
    logger.debug("bootstrap.root_created", root_id=str(SYSTEM_TENANT_ROOT_ID))


async def _setup_default_role_permissions(session: AsyncSession) -> None:
    """Set up default role permissions for the system tenant.

    These permissions apply to all resource types (GLOBAL_RESOURCE_TYPE = "*").
    """
    for role_name, perms in DEFAULT_ROLE_PERMISSIONS.items():
        for perm_name in perms:
            perm = RolePermission(
                tenant_id=SYSTEM_TENANT_ID,
                resource_type=GLOBAL_RESOURCE_TYPE,
                role_name=role_name,
                perm_name=perm_name,
            )
            session.add(perm)
    await session.flush()
    logger.debug(
        "bootstrap.permissions_created",
        roles=list(DEFAULT_ROLE_PERMISSIONS.keys()),
    )


async def _create_system_space_hierarchy(session: AsyncSession) -> None:
    """Create System Space with Official and Staging sub-spaces."""
    # System Space
    space = Resource(
        id=SYSTEM_SPACE_ID,
        tenant_id=SYSTEM_TENANT_ID,
        type="Space",
        parent_id=SYSTEM_TENANT_ROOT_ID,
        owner_principal_id=SYSTEM_PRINCIPAL_ID,
        name="System Definitions",
        status="active",
        space_kind="system",
        subspace_kind=None,  # Space itself, not a subspace
        metadata_json={"description": "System-provided definitions and resources"},
    )
    session.add(space)
    logger.debug("bootstrap.space_created", space_id=str(SYSTEM_SPACE_ID))

    # Official Subspace
    official = Resource(
        id=SYSTEM_OFFICIAL_SUBSPACE_ID,
        tenant_id=SYSTEM_TENANT_ID,
        type="Subspace",
        parent_id=SYSTEM_SPACE_ID,
        owner_principal_id=SYSTEM_PRINCIPAL_ID,
        name="System Official",
        status="active",
        space_kind="system",
        subspace_kind="official",
        metadata_json={"description": "Production-ready system definitions"},
    )
    session.add(official)
    logger.debug(
        "bootstrap.subspace_created",
        subspace_id=str(SYSTEM_OFFICIAL_SUBSPACE_ID),
        kind="official",
    )

    # Staging Subspace
    staging = Resource(
        id=SYSTEM_STAGING_SUBSPACE_ID,
        tenant_id=SYSTEM_TENANT_ID,
        type="Subspace",
        parent_id=SYSTEM_SPACE_ID,
        owner_principal_id=SYSTEM_PRINCIPAL_ID,
        name="System Staging",
        status="active",
        space_kind="system",
        subspace_kind="staging",
        metadata_json={"description": "System definitions under review"},
    )
    session.add(staging)
    logger.debug(
        "bootstrap.subspace_created",
        subspace_id=str(SYSTEM_STAGING_SUBSPACE_ID),
        kind="staging",
    )

    await session.flush()


async def _create_system_project(session: AsyncSession) -> None:
    """Create the System Project for definitions.

    All built-in definitions (pipelines, stores, accessors, ops)
    are created under this project in the Official subspace.
    """
    project = Resource(
        id=SYSTEM_PROJECT_ID,
        tenant_id=SYSTEM_TENANT_ID,
        type="Project",
        parent_id=SYSTEM_OFFICIAL_SUBSPACE_ID,  # Inside Official subspace
        owner_principal_id=SYSTEM_PRINCIPAL_ID,
        name="System Definitions",
        status="active",
        space_kind="system",
        subspace_kind="official",
        metadata_json={
            "description": "Built-in pipeline, store, accessor, and op definitions"
        },
    )
    session.add(project)
    await session.flush()
    logger.debug("bootstrap.project_created", project_id=str(SYSTEM_PROJECT_ID))


async def _grant_admin_owner_role(session: AsyncSession) -> None:
    """Grant admin the owner role on System Space.

    This gives the admin full control over all system resources.
    """
    # Grant on TenantRoot (inherits to all children)
    root_binding = RoleBinding(
        tenant_id=SYSTEM_TENANT_ID,
        principal_id=SYSTEM_PRINCIPAL_ID,
        scope_resource_id=SYSTEM_TENANT_ROOT_ID,
        role_name="owner",
        granted_by=SYSTEM_PRINCIPAL_ID,
    )
    session.add(root_binding)

    await session.flush()
    logger.debug(
        "bootstrap.admin_role_granted",
        admin_id=str(SYSTEM_PRINCIPAL_ID),
        scope_id=str(SYSTEM_TENANT_ROOT_ID),
        role="owner",
    )


# =============================================================================
# Utility Functions
# =============================================================================


def get_system_ids() -> dict[str, UUID]:
    """Get all well-known system IDs.

    Useful for SDK and tests that need to reference system entities.

    Returns:
        Dict mapping name to UUID
    """
    return {
        "tenant_id": SYSTEM_TENANT_ID,
        "principal_id": SYSTEM_PRINCIPAL_ID,
        "tenant_root_id": SYSTEM_TENANT_ROOT_ID,
        "space_id": SYSTEM_SPACE_ID,
        "official_subspace_id": SYSTEM_OFFICIAL_SUBSPACE_ID,
        "staging_subspace_id": SYSTEM_STAGING_SUBSPACE_ID,
        "project_id": SYSTEM_PROJECT_ID,
    }
