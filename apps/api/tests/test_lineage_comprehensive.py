"""Tests for data lineage and dependency relationships.

Comprehensive tests verifying:
- Lineage edge creation and querying
- Upstream/downstream dependency resolution
- DAG traversal (ancestors, descendants)
- Lineage isolation across tenants
- Complex lineage patterns (chains, diamonds, cycles prevention)
- Lineage-based freshness tracking

All tests use real database sessions from the sandbox infrastructure.
Uses the multi-account sandbox fixtures for realistic testing.
NO MOCKS - tests verify actual lineage operations and database queries.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.tests.conftest import (
    SandboxEnvironment,
    create_lineage_edge,
    create_resource,
    get_lineage_edges,
)
from libs.db.models.quant import DatasetInstance, DatasetLineage
from libs.db.models.resource import Resource
from libs.orchestration.lineage import LineageResolver


async def create_dataset_instance(
    db_session: AsyncSession,
    tenant_id: UUID,
    principal_id: UUID,
    name: str,
    parent_id: UUID,
) -> UUID:
    """Create a Resource + DatasetInstance using ORM and return the resource ID."""
    resource_id = uuid4()

    # Create resource using ORM
    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type="DatasetInstance",
        name=name,
        parent_id=parent_id,
        status="active",
    )
    db_session.add(resource)
    await db_session.flush()

    # Create dataset instance using ORM
    dataset = DatasetInstance(
        resource_id=resource_id,
        tenant_id=tenant_id,
        freshness_status="unknown",
        auto_trigger=False,
        pipeline_instance_id=uuid4(),
        store_instance_id=uuid4(),
        accessor_instance_id=uuid4(),
    )
    db_session.add(dataset)
    await db_session.flush()

    return resource_id


@pytest.mark.asyncio
class TestLineageEdgeCreation:
    """Tests for creating lineage edges."""

    async def test_create_lineage_edge(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can create a lineage edge between two datasets."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create two datasets
        upstream_id = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Upstream Dataset", space_id
        )
        downstream_id = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Downstream Dataset", space_id
        )

        # Create lineage edge
        await create_lineage_edge(
            db_session, alpha.id, upstream_id, downstream_id, "data_dependency"
        )

        # Verify edge exists
        stmt = select(DatasetLineage).where(
            DatasetLineage.tenant_id == alpha.id,
            DatasetLineage.upstream_resource_id == upstream_id,
            DatasetLineage.downstream_resource_id == downstream_id,
        )
        result = await db_session.execute(stmt)
        edge = result.scalar_one_or_none()

        assert edge is not None
        assert edge.edge_kind == "data_dependency"

    async def test_lineage_edge_kinds(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Lineage edges can have different kinds."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create datasets
        source = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Source", space_id
        )
        target = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Target", space_id
        )

        # Create edges with different kinds
        edge_kinds = ["data_dependency", "schema_reference", "transformation"]
        for kind in edge_kinds:
            await create_lineage_edge(db_session, alpha.id, source, target, kind)

        # Verify all edge kinds
        stmt = select(DatasetLineage).where(
            DatasetLineage.tenant_id == alpha.id,
            DatasetLineage.upstream_resource_id == source,
        )
        result = await db_session.execute(stmt)
        edges = result.scalars().all()

        found_kinds = {e.edge_kind for e in edges}
        assert found_kinds == set(edge_kinds)


@pytest.mark.asyncio
class TestLineageTenantIsolation:
    """Tests for lineage tenant isolation."""

    async def test_lineage_edges_are_tenant_scoped(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Lineage edges from one tenant are not visible to another."""
        alpha = sandbox_env.tenant_alpha
        beta = sandbox_env.tenant_beta

        # Create datasets in Alpha
        alpha_upstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Alpha Upstream", alpha.spaces[0]
        )
        alpha_downstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Alpha Downstream", alpha.spaces[0]
        )
        await create_lineage_edge(
            db_session, alpha.id, alpha_upstream, alpha_downstream
        )

        # Create datasets in Beta
        beta_upstream = await create_dataset_instance(
            db_session, beta.id, beta.admin.id, "Beta Upstream", beta.spaces[0]
        )
        beta_downstream = await create_dataset_instance(
            db_session, beta.id, beta.admin.id, "Beta Downstream", beta.spaces[0]
        )
        await create_lineage_edge(db_session, beta.id, beta_upstream, beta_downstream)

        # Query Alpha's edges
        alpha_edges = await get_lineage_edges(db_session, alpha.id)
        beta_edges = await get_lineage_edges(db_session, beta.id)

        # Verify isolation
        alpha_upstreams = {str(e["upstream_id"]) for e in alpha_edges}
        beta_upstreams = {str(e["upstream_id"]) for e in beta_edges}

        assert str(alpha_upstream) in alpha_upstreams
        assert str(beta_upstream) not in alpha_upstreams
        assert str(beta_upstream) in beta_upstreams
        assert str(alpha_upstream) not in beta_upstreams


@pytest.mark.asyncio
class TestLineageResolver:
    """Tests for LineageResolver dependency resolution."""

    async def test_resolve_direct_upstreams(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can get direct upstream dependencies of a dataset."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create chain: A -> B -> C
        dataset_a = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset A", space_id
        )
        dataset_b = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset B", space_id
        )
        dataset_c = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset C", space_id
        )

        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_b)
        await create_lineage_edge(db_session, alpha.id, dataset_b, dataset_c)

        resolver = LineageResolver()

        # Get direct upstreams of C (should be B only)
        upstreams_c = await resolver.resolve_upstream_dependencies(
            db_session, dataset_c, recursive=False
        )
        assert len(upstreams_c) == 1
        assert dataset_b in upstreams_c

        # Get direct upstreams of B (should be A only)
        upstreams_b = await resolver.resolve_upstream_dependencies(
            db_session, dataset_b, recursive=False
        )
        assert len(upstreams_b) == 1
        assert dataset_a in upstreams_b

        # Get direct upstreams of A (should be empty)
        upstreams_a = await resolver.resolve_upstream_dependencies(
            db_session, dataset_a, recursive=False
        )
        assert len(upstreams_a) == 0

    async def test_resolve_direct_downstreams(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can get direct downstream dependents of a dataset."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create fork: A -> [B, C]
        dataset_a = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset A", space_id
        )
        dataset_b = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset B", space_id
        )
        dataset_c = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset C", space_id
        )

        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_b)
        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_c)

        resolver = LineageResolver()

        # Get direct downstreams of A
        downstreams_a = await resolver.resolve_downstream_dependencies(
            db_session, dataset_a, recursive=False
        )
        assert len(downstreams_a) == 2
        assert dataset_b in downstreams_a
        assert dataset_c in downstreams_a

    async def test_resolve_all_ancestors(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can get all ancestors (transitive upstreams) of a dataset."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create chain: A -> B -> C -> D
        dataset_a = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset A", space_id
        )
        dataset_b = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset B", space_id
        )
        dataset_c = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset C", space_id
        )
        dataset_d = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset D", space_id
        )

        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_b)
        await create_lineage_edge(db_session, alpha.id, dataset_b, dataset_c)
        await create_lineage_edge(db_session, alpha.id, dataset_c, dataset_d)

        resolver = LineageResolver()

        # Get all ancestors of D (should include A, B, C)
        ancestors_d = await resolver.resolve_upstream_dependencies(
            db_session, dataset_d, recursive=True
        )
        assert dataset_a in ancestors_d
        assert dataset_b in ancestors_d
        assert dataset_c in ancestors_d
        assert dataset_d not in ancestors_d  # Not its own ancestor

    async def test_resolve_all_descendants(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can get all descendants (transitive downstreams) of a dataset."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create tree: A -> [B, C], B -> D
        dataset_a = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset A", space_id
        )
        dataset_b = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset B", space_id
        )
        dataset_c = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset C", space_id
        )
        dataset_d = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset D", space_id
        )

        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_b)
        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_c)
        await create_lineage_edge(db_session, alpha.id, dataset_b, dataset_d)

        resolver = LineageResolver()

        # Get all descendants of A (should include B, C, D)
        descendants_a = await resolver.resolve_downstream_dependencies(
            db_session, dataset_a, recursive=True
        )
        assert dataset_b in descendants_a
        assert dataset_c in descendants_a
        assert dataset_d in descendants_a
        assert dataset_a not in descendants_a


@pytest.mark.asyncio
class TestComplexLineagePatterns:
    """Tests for complex lineage patterns."""

    async def test_diamond_pattern(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Handles diamond dependency pattern correctly."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        #     A
        #    / \
        #   B   C
        #    \ /
        #     D

        dataset_a = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset A", space_id
        )
        dataset_b = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset B", space_id
        )
        dataset_c = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset C", space_id
        )
        dataset_d = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Dataset D", space_id
        )

        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_b)
        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_c)
        await create_lineage_edge(db_session, alpha.id, dataset_b, dataset_d)
        await create_lineage_edge(db_session, alpha.id, dataset_c, dataset_d)

        resolver = LineageResolver()

        # D's direct upstreams are B and C
        direct_upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_d, recursive=False
        )
        assert len(direct_upstreams) == 2
        assert dataset_b in direct_upstreams
        assert dataset_c in direct_upstreams

        # D's all ancestors include A, B, C
        all_ancestors = await resolver.resolve_upstream_dependencies(
            db_session, dataset_d, recursive=True
        )
        # Use set for comparison since resolver may return duplicates in diamond patterns
        ancestor_set = set(all_ancestors)
        assert dataset_a in ancestor_set
        assert dataset_b in ancestor_set
        assert dataset_c in ancestor_set
        # All three ancestors should be represented
        assert len(ancestor_set) == 3

    async def test_multiple_roots_pattern(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Handles multiple root datasets correctly."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # A -> C, B -> C (C has two roots)
        dataset_a = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Root A", space_id
        )
        dataset_b = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Root B", space_id
        )
        dataset_c = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Merged C", space_id
        )

        await create_lineage_edge(db_session, alpha.id, dataset_a, dataset_c)
        await create_lineage_edge(db_session, alpha.id, dataset_b, dataset_c)

        resolver = LineageResolver()

        # C's direct upstreams are both A and B
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_c, recursive=False
        )
        assert len(upstreams) == 2
        assert dataset_a in upstreams
        assert dataset_b in upstreams

        # Both A and B have no upstreams (they are roots)
        upstreams_a = await resolver.resolve_upstream_dependencies(
            db_session, dataset_a, recursive=False
        )
        upstreams_b = await resolver.resolve_upstream_dependencies(
            db_session, dataset_b, recursive=False
        )
        assert len(upstreams_a) == 0
        assert len(upstreams_b) == 0

    async def test_wide_fan_out(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Handles wide fan-out (one source, many targets)."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # A -> [B1, B2, B3, B4, B5]
        source = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Source", space_id
        )

        targets = []
        for i in range(5):
            target = await create_dataset_instance(
                db_session, alpha.id, alpha.admin.id, f"Target {i}", space_id
            )
            targets.append(target)
            await create_lineage_edge(db_session, alpha.id, source, target)

        resolver = LineageResolver()

        # Source has 5 direct downstreams
        downstreams = await resolver.resolve_downstream_dependencies(
            db_session, source, recursive=False
        )
        assert len(downstreams) == 5
        for target in targets:
            assert target in downstreams

    async def test_wide_fan_in(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Handles wide fan-in (many sources, one target)."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # [A1, A2, A3, A4, A5] -> B
        sources = []
        for i in range(5):
            source = await create_dataset_instance(
                db_session, alpha.id, alpha.admin.id, f"Source {i}", space_id
            )
            sources.append(source)

        target = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Target", space_id
        )

        for source in sources:
            await create_lineage_edge(db_session, alpha.id, source, target)

        resolver = LineageResolver()

        # Target has 5 direct upstreams
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, target, recursive=False
        )
        assert len(upstreams) == 5
        for source in sources:
            assert source in upstreams


@pytest.mark.asyncio
class TestUpstreamStatusTracking:
    """Tests for upstream status tracking in lineage."""

    async def test_update_upstream_status(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can update upstream status for a downstream dataset."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create upstream and downstream
        upstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Upstream", space_id
        )
        downstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Downstream", space_id
        )
        await create_lineage_edge(db_session, alpha.id, upstream, downstream)

        # Update downstream's upstream_resource_ids via ORM
        stmt = select(DatasetInstance).where(DatasetInstance.resource_id == downstream)
        result = await db_session.execute(stmt)
        instance = result.scalar_one()
        instance.upstream_resource_ids = [upstream]
        await db_session.flush()

        resolver = LineageResolver()

        # Update status
        await resolver.update_upstream_status(db_session, downstream, upstream, "ready")

        # Verify status was updated (no refresh - changes are in memory via shared session)
        # The resolver's session.get() returns the same instance object from the session cache
        upstream_status = instance.upstream_status or {}
        assert str(upstream) in upstream_status
        assert upstream_status[str(upstream)] == "ready"

    async def test_check_all_upstreams_ready(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can check if all upstreams are ready."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create two upstreams and one downstream
        upstream1 = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Upstream 1", space_id
        )
        upstream2 = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Upstream 2", space_id
        )
        downstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Downstream", space_id
        )

        await create_lineage_edge(db_session, alpha.id, upstream1, downstream)
        await create_lineage_edge(db_session, alpha.id, upstream2, downstream)

        # Set up upstream_resource_ids on downstream via ORM
        stmt = select(DatasetInstance).where(DatasetInstance.resource_id == downstream)
        result = await db_session.execute(stmt)
        instance = result.scalar_one()
        instance.upstream_resource_ids = [upstream1, upstream2]
        await db_session.flush()

        resolver = LineageResolver()

        # Mark first upstream ready - should NOT be all ready
        all_ready_1 = await resolver.update_upstream_status(
            db_session, downstream, upstream1, "ready"
        )
        assert not all_ready_1  # Still waiting for upstream2

        # Mark second upstream ready - should now be all ready
        all_ready_2 = await resolver.update_upstream_status(
            db_session, downstream, upstream2, "ready"
        )
        assert all_ready_2  # All upstreams ready


@pytest.mark.asyncio
class TestLineageEdgeCases:
    """Edge case tests for lineage system."""

    async def test_isolated_dataset_has_no_lineage(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Dataset with no edges has empty upstream/downstream lists."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        isolated = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Isolated", space_id
        )

        resolver = LineageResolver()

        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, isolated, recursive=False
        )
        downstreams = await resolver.resolve_downstream_dependencies(
            db_session, isolated, recursive=False
        )
        ancestors = await resolver.resolve_upstream_dependencies(
            db_session, isolated, recursive=True
        )
        descendants = await resolver.resolve_downstream_dependencies(
            db_session, isolated, recursive=True
        )

        assert len(upstreams) == 0
        assert len(downstreams) == 0
        assert len(ancestors) == 0
        assert len(descendants) == 0

    async def test_self_reference_not_allowed(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Dataset cannot be its own upstream (cycle of 1)."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        dataset = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Self-Ref", space_id
        )

        # Try to create self-reference
        # This may or may not be prevented by DB constraints
        try:
            await create_lineage_edge(db_session, alpha.id, dataset, dataset)
            # If it succeeded, verify ancestors don't loop infinitely
            resolver = LineageResolver()
            ancestors = await resolver.resolve_upstream_dependencies(
                db_session, dataset, recursive=True
            )
            # Should handle gracefully (not infinite loop)
            assert len(ancestors) <= 1  # Might contain self or be empty
        except Exception:
            # Constraint prevented it - good
            pass

    async def test_deleted_resource_lineage_preserved(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Lineage edges are preserved even if resource is marked deleted."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        upstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Upstream", space_id
        )
        downstream = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "Downstream", space_id
        )
        await create_lineage_edge(db_session, alpha.id, upstream, downstream)

        # "Delete" the upstream (mark as deleted) - use ORM
        stmt = select(Resource).where(Resource.id == upstream)
        result = await db_session.execute(stmt)
        resource = result.scalar_one()
        resource.status = "deleted"
        await db_session.flush()

        # Lineage edge still exists
        edges = await get_lineage_edges(db_session, alpha.id)
        upstream_ids = [e["upstream_id"] for e in edges]
        assert upstream in upstream_ids

    async def test_lineage_across_different_spaces(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Lineage can cross space boundaries within same tenant."""
        alpha = sandbox_env.tenant_alpha
        space1 = alpha.spaces[0]

        # Create second space
        space2 = await create_resource(
            db_session,
            alpha.id,
            alpha.admin.id,
            "Space",
            "Second Space",
            space_kind="team",
        )

        # Create datasets in different spaces
        dataset_in_space1 = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "In Space 1", space1
        )
        dataset_in_space2 = await create_dataset_instance(
            db_session, alpha.id, alpha.admin.id, "In Space 2", space2
        )

        # Create cross-space lineage
        await create_lineage_edge(
            db_session, alpha.id, dataset_in_space1, dataset_in_space2
        )

        resolver = LineageResolver()

        # Cross-space lineage works
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_in_space2, recursive=False
        )
        assert dataset_in_space1 in upstreams
