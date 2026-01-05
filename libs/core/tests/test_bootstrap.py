"""Tests for System Bootstrap Service."""

from uuid import UUID

import pytest
from sqlalchemy import select

from libs.core.bootstrap import (
    bootstrap_system,
    get_system_ids,
    SYSTEM_TENANT_ID,
    SYSTEM_PRINCIPAL_ID,
    SYSTEM_TENANT_ROOT_ID,
    SYSTEM_SPACE_ID,
    SYSTEM_OFFICIAL_SUBSPACE_ID,
    SYSTEM_STAGING_SUBSPACE_ID,
    SYSTEM_PROJECT_ID,
    DEFAULT_ROLE_PERMISSIONS,
)
from libs.db.models.identity import Tenant, Principal
from libs.db.models.resource import Resource
from libs.db.models.rbac import RoleBinding, RolePermission


class TestBootstrapSystem:
    """Test bootstrap_system() function."""

    @pytest.mark.asyncio
    async def test_bootstrap_creates_system_tenant(self, db_session) -> None:
        """Verify bootstrap creates system tenant."""
        result = await bootstrap_system(db_session)

        assert result.created is True
        assert result.tenant_id == SYSTEM_TENANT_ID

        # Verify tenant exists
        tenant = await db_session.get(Tenant, SYSTEM_TENANT_ID)
        assert tenant is not None
        assert tenant.name == "OptAIC System"

    @pytest.mark.asyncio
    async def test_bootstrap_creates_admin_principal(self, db_session) -> None:
        """Verify bootstrap creates admin principal."""
        result = await bootstrap_system(db_session)

        assert result.admin_principal_id == SYSTEM_PRINCIPAL_ID

        # Verify principal exists
        admin = await db_session.get(Principal, SYSTEM_PRINCIPAL_ID)
        assert admin is not None
        assert admin.display_name == "System Administrator"
        assert admin.email == "admin@optaic.local"
        assert admin.kind == "user"
        assert admin.status == "active"

    @pytest.mark.asyncio
    async def test_bootstrap_creates_tenant_root(self, db_session) -> None:
        """Verify bootstrap creates TenantRoot resource."""
        await bootstrap_system(db_session)

        root = await db_session.get(Resource, SYSTEM_TENANT_ROOT_ID)
        assert root is not None
        assert root.type == "TenantRoot"
        assert root.name == "OptAIC System Root"
        assert root.parent_id is None
        assert root.owner_principal_id == SYSTEM_PRINCIPAL_ID
        assert root.space_kind == "system"

    @pytest.mark.asyncio
    async def test_bootstrap_creates_system_space(self, db_session) -> None:
        """Verify bootstrap creates System Space."""
        result = await bootstrap_system(db_session)

        assert result.system_space_id == SYSTEM_SPACE_ID

        space = await db_session.get(Resource, SYSTEM_SPACE_ID)
        assert space is not None
        assert space.type == "Space"
        assert space.name == "System Definitions"
        assert space.parent_id == SYSTEM_TENANT_ROOT_ID
        assert space.space_kind == "system"
        assert space.subspace_kind is None

    @pytest.mark.asyncio
    async def test_bootstrap_creates_official_subspace(self, db_session) -> None:
        """Verify bootstrap creates Official subspace."""
        result = await bootstrap_system(db_session)

        assert result.official_subspace_id == SYSTEM_OFFICIAL_SUBSPACE_ID

        official = await db_session.get(Resource, SYSTEM_OFFICIAL_SUBSPACE_ID)
        assert official is not None
        assert official.type == "Subspace"
        assert official.name == "System Official"
        assert official.parent_id == SYSTEM_SPACE_ID
        assert official.space_kind == "system"
        assert official.subspace_kind == "official"

    @pytest.mark.asyncio
    async def test_bootstrap_creates_staging_subspace(self, db_session) -> None:
        """Verify bootstrap creates Staging subspace."""
        result = await bootstrap_system(db_session)

        assert result.staging_subspace_id == SYSTEM_STAGING_SUBSPACE_ID

        staging = await db_session.get(Resource, SYSTEM_STAGING_SUBSPACE_ID)
        assert staging is not None
        assert staging.type == "Subspace"
        assert staging.name == "System Staging"
        assert staging.parent_id == SYSTEM_SPACE_ID
        assert staging.space_kind == "system"
        assert staging.subspace_kind == "staging"

    @pytest.mark.asyncio
    async def test_bootstrap_creates_system_project(self, db_session) -> None:
        """Verify bootstrap creates System Project for definitions."""
        result = await bootstrap_system(db_session)

        assert result.project_id == SYSTEM_PROJECT_ID

        project = await db_session.get(Resource, SYSTEM_PROJECT_ID)
        assert project is not None
        assert project.type == "Project"
        assert project.name == "System Definitions"
        assert project.parent_id == SYSTEM_OFFICIAL_SUBSPACE_ID
        assert project.space_kind == "system"
        assert project.subspace_kind == "official"

    @pytest.mark.asyncio
    async def test_bootstrap_is_idempotent(self, db_session) -> None:
        """Verify bootstrap can be called multiple times safely.

        Note: If previous tests have already bootstrapped, result1.created
        will be False. This test verifies that calling bootstrap twice
        produces consistent results regardless of initial state.
        """
        result1 = await bootstrap_system(db_session)
        result2 = await bootstrap_system(db_session)

        # Both calls should return same IDs
        assert result1.tenant_id == result2.tenant_id
        assert result1.admin_principal_id == result2.admin_principal_id
        assert result1.system_space_id == result2.system_space_id

        # Second call should never create (either both false, or first true, second false)
        assert result2.created is False

        # If first call created, second should not
        if result1.created:
            assert result2.created is False

    @pytest.mark.asyncio
    async def test_bootstrap_creates_role_permissions(self, db_session) -> None:
        """Verify bootstrap creates default role permissions."""
        await bootstrap_system(db_session)

        # Check owner role has all permissions
        owner_perms = await db_session.scalars(
            select(RolePermission).where(
                RolePermission.tenant_id == SYSTEM_TENANT_ID,
                RolePermission.role_name == "owner",
            )
        )
        owner_perm_names = {p.perm_name for p in owner_perms.all()}
        assert len(owner_perm_names) == len(DEFAULT_ROLE_PERMISSIONS["owner"])

        # Check viewer role has limited permissions
        viewer_perms = await db_session.scalars(
            select(RolePermission).where(
                RolePermission.tenant_id == SYSTEM_TENANT_ID,
                RolePermission.role_name == "viewer",
            )
        )
        viewer_perm_names = {p.perm_name for p in viewer_perms.all()}
        assert "RESOURCE_READ" in viewer_perm_names
        assert "RESOURCE_DELETE" not in viewer_perm_names

    @pytest.mark.asyncio
    async def test_bootstrap_grants_admin_owner_role(self, db_session) -> None:
        """Verify admin is granted owner role on TenantRoot."""
        await bootstrap_system(db_session)

        binding = await db_session.scalars(
            select(RoleBinding).where(
                RoleBinding.tenant_id == SYSTEM_TENANT_ID,
                RoleBinding.principal_id == SYSTEM_PRINCIPAL_ID,
                RoleBinding.scope_resource_id == SYSTEM_TENANT_ROOT_ID,
            )
        )
        admin_binding = binding.first()
        assert admin_binding is not None
        assert admin_binding.role_name == "owner"
        assert admin_binding.revoked_at is None


class TestGetSystemIds:
    """Test get_system_ids() utility function."""

    def test_get_system_ids_returns_all_ids(self) -> None:
        """Verify get_system_ids returns all well-known IDs."""
        ids = get_system_ids()

        assert ids["tenant_id"] == SYSTEM_TENANT_ID
        assert ids["principal_id"] == SYSTEM_PRINCIPAL_ID
        assert ids["tenant_root_id"] == SYSTEM_TENANT_ROOT_ID
        assert ids["space_id"] == SYSTEM_SPACE_ID
        assert ids["official_subspace_id"] == SYSTEM_OFFICIAL_SUBSPACE_ID
        assert ids["staging_subspace_id"] == SYSTEM_STAGING_SUBSPACE_ID
        assert ids["project_id"] == SYSTEM_PROJECT_ID

    def test_system_ids_are_valid_uuids(self) -> None:
        """Verify all system IDs are valid UUIDs."""
        ids = get_system_ids()

        for name, id_value in ids.items():
            assert isinstance(id_value, UUID), f"{name} is not a UUID"


class TestSpaceHierarchy:
    """Test the space hierarchy structure."""

    @pytest.mark.asyncio
    async def test_hierarchy_structure(self, db_session) -> None:
        """Verify the complete hierarchy structure.

        Expected:
        TenantRoot
        └── Space (System Definitions)
            ├── Subspace (Official)
            │   └── Project (System Definitions)
            └── Subspace (Staging)
        """
        await bootstrap_system(db_session)

        # Verify TenantRoot -> Space
        space = await db_session.get(Resource, SYSTEM_SPACE_ID)
        assert space.parent_id == SYSTEM_TENANT_ROOT_ID

        # Verify Space -> Official Subspace
        official = await db_session.get(Resource, SYSTEM_OFFICIAL_SUBSPACE_ID)
        assert official.parent_id == SYSTEM_SPACE_ID

        # Verify Space -> Staging Subspace
        staging = await db_session.get(Resource, SYSTEM_STAGING_SUBSPACE_ID)
        assert staging.parent_id == SYSTEM_SPACE_ID

        # Verify Official -> Project
        project = await db_session.get(Resource, SYSTEM_PROJECT_ID)
        assert project.parent_id == SYSTEM_OFFICIAL_SUBSPACE_ID
