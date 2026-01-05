"""Tests for GovernanceService."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.artifacts import ArtifactManager
from libs.core.governance import GovernanceService
from libs.core.rbac.models import ActorContext
from libs.db.models.identity import Principal, Tenant
from libs.db.models.rbac import RoleBinding
from libs.db.models.resource import Resource, ResourceEdge


@pytest.fixture
def artifact_manager(tmp_path: Path) -> ArtifactManager:
    """Create an ArtifactManager with a temporary directory."""
    return ArtifactManager(data_dir=tmp_path)


@pytest.fixture
def governance_service(artifact_manager: ArtifactManager) -> GovernanceService:
    """Create a GovernanceService with the test artifact manager."""
    return GovernanceService(artifact_manager=artifact_manager)


@pytest.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    """Create a test tenant."""
    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture
async def actor_principal(db_session: AsyncSession, tenant: Tenant) -> Principal:
    """Create an actor principal."""
    principal = Principal(
        id=uuid4(),
        tenant_id=tenant.id,
        kind="user",
        status="active",
        display_name="Test Actor",
    )
    db_session.add(principal)
    await db_session.flush()
    return principal


@pytest.fixture
async def other_principal(db_session: AsyncSession, tenant: Tenant) -> Principal:
    """Create another principal (for transfer tests)."""
    principal = Principal(
        id=uuid4(),
        tenant_id=tenant.id,
        kind="user",
        status="active",
        display_name="Other User",
    )
    db_session.add(principal)
    await db_session.flush()
    return principal


@pytest.fixture
async def team_principal(db_session: AsyncSession, tenant: Tenant) -> Principal:
    """Create a team principal."""
    principal = Principal(
        id=uuid4(),
        tenant_id=tenant.id,
        kind="team",
        status="active",
        display_name="Test Team",
    )
    db_session.add(principal)
    await db_session.flush()
    return principal


@pytest.fixture
def actor(tenant: Tenant, actor_principal: Principal) -> ActorContext:
    """Create an actor context."""
    return ActorContext(id=actor_principal.id, tenant_id=tenant.id)


@pytest.fixture
async def target_space(
    db_session: AsyncSession,
    tenant: Tenant,
    team_principal: Principal,
) -> Resource:
    """Create a target space resource."""
    space = Resource(
        id=uuid4(),
        tenant_id=tenant.id,
        type="Space",
        parent_id=None,
        owner_principal_id=team_principal.id,
        space_kind="team",
        subspace_kind=None,
        name="Target Space",
        status="active",
    )
    db_session.add(space)
    await db_session.flush()
    return space


@pytest.fixture
async def target_project(
    db_session: AsyncSession,
    tenant: Tenant,
    actor_principal: Principal,
    target_space: Resource,
) -> Resource:
    """Create a target project resource under the space."""
    # First create a subspace
    subspace = Resource(
        id=uuid4(),
        tenant_id=tenant.id,
        type="SubSpace",
        parent_id=target_space.id,
        owner_principal_id=actor_principal.id,
        space_kind="team",
        subspace_kind="custom",
        name="Custom SubSpace",
        status="active",
    )
    db_session.add(subspace)
    await db_session.flush()

    # Then create a project under the subspace
    project = Resource(
        id=uuid4(),
        tenant_id=tenant.id,
        type="Project",
        parent_id=subspace.id,
        owner_principal_id=actor_principal.id,
        space_kind="team",
        subspace_kind="custom",
        name="Test Project",
        status="active",
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.fixture
async def source_resource(
    db_session: AsyncSession,
    tenant: Tenant,
    actor_principal: Principal,
    artifact_manager: ArtifactManager,
    target_project: Resource,
) -> Resource:
    """Create a source resource with an artifact (SignalDef type)."""
    # Create artifact with a file
    artifact_ref = artifact_manager.create_artifact()
    artifact_manager.write_file(artifact_ref, "data.txt", b"test data")

    # Use SignalDef type which allows all governance actions
    resource = Resource(
        id=uuid4(),
        tenant_id=tenant.id,
        type="SignalDef",  # Use a definition type that allows all actions
        parent_id=target_project.id,  # Under a project
        owner_principal_id=actor_principal.id,
        space_kind="team",
        subspace_kind="custom",
        name="Source Resource",
        status="active",
        artifact_ref=artifact_ref,
    )
    db_session.add(resource)
    await db_session.flush()
    return resource


class TestGovernanceServiceCopy:
    """Tests for copy operation."""

    async def test_copy_resource(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
    ) -> None:
        """Test copying a resource by reference."""
        result = await governance_service.copy_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_project.id,
        )

        assert result["operation"] == "copy"
        assert result["source_id"] == str(source_resource.id)
        # Same artifact reference (not copied)
        assert result["artifact_ref"] == str(source_resource.artifact_ref)

        # Verify resource was created
        new_resource = await db_session.get(Resource, UUID(result["id"]))
        assert new_resource is not None
        assert new_resource.artifact_ref == source_resource.artifact_ref
        assert new_resource.parent_id == target_project.id

        # Verify lineage edge was created
        edge_result = await db_session.execute(
            select(ResourceEdge).where(
                ResourceEdge.src_resource_id == UUID(result["id"]),
                ResourceEdge.dst_resource_id == source_resource.id,
                ResourceEdge.edge_type == "copy_of",
            )
        )
        edge = edge_result.scalar_one_or_none()
        assert edge is not None

    async def test_copy_with_custom_name(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
    ) -> None:
        """Test copying a resource with a custom name."""
        result = await governance_service.copy_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_project.id,
            name="Custom Copy Name",
        )

        assert result["name"] == "Custom Copy Name"


class TestGovernanceServiceBranch:
    """Tests for branch operation."""

    async def test_branch_resource(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        artifact_manager: ArtifactManager,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
    ) -> None:
        """Test branching a resource with file copy."""
        result = await governance_service.branch_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_project.id,
        )

        assert result["operation"] == "branch"
        assert result["source_id"] == str(source_resource.id)
        # Different artifact reference (files copied)
        assert result["artifact_ref"] != str(source_resource.artifact_ref)

        # Verify files were copied
        new_artifact_ref = UUID(result["artifact_ref"])
        content = artifact_manager.read_file(new_artifact_ref, "data.txt")
        assert content == b"test data"

        # Verify RBAC bindings
        owner_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == actor.id,
                RoleBinding.scope_resource_id == UUID(result["id"]),
                RoleBinding.role_name == "owner",
            )
        )
        assert owner_binding.scalar_one_or_none() is not None

    async def test_branch_creates_viewer_for_source_owner(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        tenant: Tenant,
        other_principal: Principal,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
    ) -> None:
        """Test that branching creates viewer role for source owner."""
        # Change source owner to be different from actor
        source_resource.owner_principal_id = other_principal.id
        await db_session.flush()

        result = await governance_service.branch_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_project.id,
        )

        # Verify viewer binding for source owner
        viewer_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == other_principal.id,
                RoleBinding.scope_resource_id == UUID(result["id"]),
                RoleBinding.role_name == "viewer",
            )
        )
        assert viewer_binding.scalar_one_or_none() is not None


class TestGovernanceServiceTransfer:
    """Tests for transfer operation."""

    async def test_transfer_resource(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        other_principal: Principal,
        source_resource: Resource,
    ) -> None:
        """Test transferring ownership of a resource."""
        result = await governance_service.transfer_resource(
            db_session,
            actor,
            resource_id=source_resource.id,
            target_owner_id=other_principal.id,
        )

        assert result["operation"] == "transfer"
        assert result["previous_owner_id"] == str(actor.id)
        assert result["owner_id"] == str(other_principal.id)

        # Verify resource ownership changed
        await db_session.refresh(source_resource)
        assert source_resource.owner_principal_id == other_principal.id

        # Verify new owner has owner role
        new_owner_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == other_principal.id,
                RoleBinding.scope_resource_id == source_resource.id,
                RoleBinding.role_name == "owner",
                RoleBinding.revoked_at.is_(None),
            )
        )
        assert new_owner_binding.scalar_one_or_none() is not None

        # Verify previous owner has viewer role
        prev_owner_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == actor.id,
                RoleBinding.scope_resource_id == source_resource.id,
                RoleBinding.role_name == "viewer",
                RoleBinding.revoked_at.is_(None),
            )
        )
        assert prev_owner_binding.scalar_one_or_none() is not None

    async def test_transfer_requires_owner(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        tenant: Tenant,
        other_principal: Principal,
        source_resource: Resource,
    ) -> None:
        """Test that only the owner can transfer a resource."""
        # Create actor who is not the owner
        non_owner_actor = ActorContext(id=other_principal.id, tenant_id=tenant.id)

        with pytest.raises(ValueError, match="Only the owner can transfer"):
            await governance_service.transfer_resource(
                db_session,
                non_owner_actor,
                resource_id=source_resource.id,
                target_owner_id=uuid4(),
            )


class TestGovernanceServicePromote:
    """Tests for promote operation."""

    async def test_promote_resource(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        artifact_manager: ArtifactManager,
        actor: ActorContext,
        source_resource: Resource,
        target_space: Resource,
        team_principal: Principal,
    ) -> None:
        """Test promoting a resource to a team space (goes to staging)."""
        result = await governance_service.promote_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_space_id=target_space.id,
            team_principal_id=team_principal.id,
        )

        assert result["operation"] == "promote"
        assert result["source_id"] == str(source_resource.id)
        assert result["team_principal_id"] == str(team_principal.id)
        assert result["subspace_kind"] == "staging"  # Promotes to staging first
        assert result["status"] == "pending_approval"

        # Verify artifact was copied
        assert result["artifact_ref"] != str(source_resource.artifact_ref)
        new_artifact_ref = UUID(result["artifact_ref"])
        content = artifact_manager.read_file(new_artifact_ref, "data.txt")
        assert content == b"test data"

        # Verify resource was created with correct ownership
        new_resource = await db_session.get(Resource, UUID(result["id"]))
        assert new_resource is not None
        assert new_resource.owner_principal_id == team_principal.id
        assert new_resource.space_kind == "team"
        assert new_resource.subspace_kind == "staging"  # In staging, not official
        assert new_resource.status == "pending_approval"

        # Verify team has owner role
        team_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == team_principal.id,
                RoleBinding.scope_resource_id == UUID(result["id"]),
                RoleBinding.role_name == "owner",
            )
        )
        assert team_binding.scalar_one_or_none() is not None

        # Verify promoter has delegator role
        promoter_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == actor.id,
                RoleBinding.scope_resource_id == UUID(result["id"]),
                RoleBinding.role_name == "delegator",
            )
        )
        assert promoter_binding.scalar_one_or_none() is not None

        # Verify promotion request was created
        assert "promotion_request_id" in result


class TestGovernanceServiceMerge:
    """Tests for merge operation."""

    async def test_merge_resource(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        artifact_manager: ArtifactManager,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
    ) -> None:
        """Test merging a branch back to its ancestor."""
        # First, create a branch
        branch_result = await governance_service.branch_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_project.id,
        )
        branch_id = UUID(branch_result["id"])
        branch_artifact_ref = UUID(branch_result["artifact_ref"])

        # Modify the branch's artifact
        artifact_manager.write_file(branch_artifact_ref, "data.txt", b"modified data")

        # Merge branch back to source
        merge_result = await governance_service.merge_resource(
            db_session,
            actor,
            source_id=branch_id,
            target_id=source_resource.id,
        )

        assert merge_result["operation"] == "merge"
        assert merge_result["source_id"] == str(branch_id)
        assert merge_result["target_id"] == str(source_resource.id)

        # Verify source artifact was replaced
        await db_session.refresh(source_resource)
        assert source_resource.artifact_ref == branch_artifact_ref

        # Verify branch is marked as merged
        branch = await db_session.get(Resource, branch_id)
        assert branch is not None
        assert branch.status == "merged"

        # Verify merge edge was created
        edge_result = await db_session.execute(
            select(ResourceEdge).where(
                ResourceEdge.src_resource_id == source_resource.id,
                ResourceEdge.dst_resource_id == branch_id,
                ResourceEdge.edge_type == "merged_from",
            )
        )
        edge = edge_result.scalar_one_or_none()
        assert edge is not None

    async def test_merge_requires_branch_relationship(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
        tenant: Tenant,
        actor_principal: Principal,
    ) -> None:
        """Test that merge fails if source is not a branch of target."""
        # Create an unrelated resource (using SignalDef type)
        unrelated = Resource(
            id=uuid4(),
            tenant_id=tenant.id,
            type="SignalDef",
            parent_id=target_project.id,
            owner_principal_id=actor_principal.id,
            name="Unrelated Resource",
            status="active",
        )
        db_session.add(unrelated)
        await db_session.flush()

        with pytest.raises(ValueError, match="is not a branch of"):
            await governance_service.merge_resource(
                db_session,
                actor,
                source_id=unrelated.id,
                target_id=source_resource.id,
            )


class TestGovernanceServiceLineage:
    """Tests for lineage queries."""

    async def test_get_resource_lineage_upstream(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        source_resource: Resource,
        target_project: Resource,
    ) -> None:
        """Test getting upstream lineage."""
        # Create a branch
        branch_result = await governance_service.branch_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_project.id,
        )
        branch_id = UUID(branch_result["id"])

        # Get upstream lineage
        lineage = await governance_service.get_resource_lineage(
            db_session,
            actor,
            branch_id,
            direction="upstream",
        )

        assert len(lineage) == 1
        assert lineage[0]["id"] == str(source_resource.id)
        assert lineage[0]["name"] == source_resource.name
