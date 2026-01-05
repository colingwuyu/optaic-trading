# Testing Governance Operations

## Fixture Setup

```python
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.artifacts import ArtifactManager
from libs.core.governance import GovernanceService
from libs.core.rbac.models import ActorContext
from libs.db.models.identity import Principal, Tenant
from libs.db.models.resource import Resource, ResourceEdge


@pytest.fixture
def artifact_manager(tmp_path: Path) -> ArtifactManager:
    """Use temp directory for test artifacts."""
    return ArtifactManager(data_dir=tmp_path)


@pytest.fixture
def governance_service(artifact_manager: ArtifactManager) -> GovernanceService:
    return GovernanceService(artifact_manager=artifact_manager)


@pytest.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    tenant = Tenant(id=uuid4(), name="Test Tenant")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture
async def actor_principal(db_session: AsyncSession, tenant: Tenant) -> Principal:
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
def actor(tenant: Tenant, actor_principal: Principal) -> ActorContext:
    return ActorContext(id=actor_principal.id, tenant_id=tenant.id)


@pytest.fixture
async def source_resource(
    db_session: AsyncSession,
    tenant: Tenant,
    actor_principal: Principal,
    artifact_manager: ArtifactManager,
) -> Resource:
    # Create artifact with test file
    artifact_ref = artifact_manager.create_artifact()
    artifact_manager.write_file(artifact_ref, "data.txt", b"test data")

    resource = Resource(
        id=uuid4(),
        tenant_id=tenant.id,
        type="TestResource",
        owner_principal_id=actor_principal.id,
        name="Source Resource",
        status="active",
        artifact_ref=artifact_ref,
    )
    db_session.add(resource)
    await db_session.flush()
    return resource
```

## Testing Copy Operations

```python
class TestGovernanceServiceCopy:
    async def test_copy_resource(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        source_resource: Resource,
        target_space: Resource,
    ) -> None:
        result = await governance_service.copy_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_space.id,
        )

        # Verify same artifact (no copy)
        assert result["artifact_ref"] == str(source_resource.artifact_ref)

        # Verify lineage edge
        edge_result = await db_session.execute(
            select(ResourceEdge).where(
                ResourceEdge.src_resource_id == UUID(result["id"]),
                ResourceEdge.edge_type == "copy_of",
            )
        )
        assert edge_result.scalar_one_or_none() is not None
```

## Testing Branch Operations

```python
class TestGovernanceServiceBranch:
    async def test_branch_creates_new_artifact(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        artifact_manager: ArtifactManager,
        actor: ActorContext,
        source_resource: Resource,
        target_space: Resource,
    ) -> None:
        result = await governance_service.branch_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_parent_id=target_space.id,
        )

        # Different artifact (files copied)
        assert result["artifact_ref"] != str(source_resource.artifact_ref)

        # Verify files were copied
        new_artifact_ref = UUID(result["artifact_ref"])
        content = artifact_manager.read_file(new_artifact_ref, "data.txt")
        assert content == b"test data"

    async def test_branch_creates_rbac_bindings(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        source_resource: Resource,
        target_space: Resource,
    ) -> None:
        result = await governance_service.branch_resource(...)

        # Actor is owner
        owner_binding = await db_session.execute(
            select(RoleBinding).where(
                RoleBinding.principal_id == actor.id,
                RoleBinding.scope_resource_id == UUID(result["id"]),
                RoleBinding.role_name == "owner",
            )
        )
        assert owner_binding.scalar_one_or_none() is not None
```

## Testing Transfer Operations

```python
class TestGovernanceServiceTransfer:
    async def test_transfer_changes_ownership(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        actor: ActorContext,
        other_principal: Principal,
        source_resource: Resource,
    ) -> None:
        result = await governance_service.transfer_resource(
            db_session,
            actor,
            resource_id=source_resource.id,
            target_owner_id=other_principal.id,
        )

        # Verify ownership changed
        await db_session.refresh(source_resource)
        assert source_resource.owner_principal_id == other_principal.id

    async def test_transfer_requires_owner(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        tenant: Tenant,
        other_principal: Principal,
        source_resource: Resource,
    ) -> None:
        non_owner = ActorContext(id=other_principal.id, tenant_id=tenant.id)

        with pytest.raises(ValueError, match="Only the owner can transfer"):
            await governance_service.transfer_resource(
                db_session,
                non_owner,
                resource_id=source_resource.id,
                target_owner_id=uuid4(),
            )
```

## Testing Promote Operations

```python
class TestGovernanceServicePromote:
    async def test_promote_copies_artifact_to_team(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        artifact_manager: ArtifactManager,
        actor: ActorContext,
        source_resource: Resource,
        target_space: Resource,
        team_principal: Principal,
    ) -> None:
        result = await governance_service.promote_resource(
            db_session,
            actor,
            source_id=source_resource.id,
            target_space_id=target_space.id,
            team_principal_id=team_principal.id,
        )

        # Verify new artifact
        assert result["artifact_ref"] != str(source_resource.artifact_ref)

        # Verify team is owner
        new_resource = await db_session.get(Resource, UUID(result["id"]))
        assert new_resource.owner_principal_id == team_principal.id
        assert new_resource.space_kind == "team"
```

## Testing Merge Operations

```python
class TestGovernanceServiceMerge:
    async def test_merge_replaces_ancestor_artifact(
        self,
        db_session: AsyncSession,
        governance_service: GovernanceService,
        artifact_manager: ArtifactManager,
        actor: ActorContext,
        source_resource: Resource,
        target_space: Resource,
    ) -> None:
        # Create branch first
        branch_result = await governance_service.branch_resource(
            db_session, actor,
            source_id=source_resource.id,
            target_parent_id=target_space.id,
        )
        branch_id = UUID(branch_result["id"])
        branch_artifact_ref = UUID(branch_result["artifact_ref"])

        # Modify branch
        artifact_manager.write_file(branch_artifact_ref, "data.txt", b"modified")

        # Merge
        merge_result = await governance_service.merge_resource(
            db_session, actor,
            source_id=branch_id,
            target_id=source_resource.id,
        )

        # Verify ancestor has branch artifact
        await db_session.refresh(source_resource)
        assert source_resource.artifact_ref == branch_artifact_ref
```

## Assertions Checklist

For each governance operation, verify:

- [ ] Correct artifact handling (copied vs shared)
- [ ] Lineage edge created with correct type
- [ ] RBAC bindings created/modified as expected
- [ ] Activity emitted with correct action
- [ ] Resource ownership set correctly
- [ ] Space/subspace kind set correctly
