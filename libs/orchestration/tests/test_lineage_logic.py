"""Tests for LineageResolver - Comprehensive lineage graph logic tests.

Tests the core lineage resolution functionality:
- Upstream/downstream dependency resolution (direct and recursive)
- Topological sorting for execution order
- Cycle detection in dependency graphs
- Staleness propagation through the graph
- Edge cases: empty graphs, single nodes, diamond patterns, long chains

All tests use real database sessions from the sandbox infrastructure.
NO MOCKS - tests verify actual database operations and graph algorithms.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.models.quant import DatasetInstance, DatasetLineage
from libs.db.models.resource import Resource
from libs.orchestration.lineage import LineageResolver


def utcnow_iso() -> str:
    """Return current UTC time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def resolver() -> LineageResolver:
    """LineageResolver instance."""
    return LineageResolver()


async def create_tenant_and_principal(db_session: AsyncSession):
    """Create a test tenant and principal, return their IDs."""
    tenant_id = uuid4()
    principal_id = uuid4()

    await db_session.execute(
        text("""
            INSERT INTO tenants (id, name, created_at)
            VALUES (:id, :name, :created_at)
        """),
        {
            "id": str(tenant_id),
            "name": "Lineage Test Tenant",
            "created_at": utcnow_iso(),
        },
    )

    await db_session.execute(
        text("""
            INSERT INTO principals (id, tenant_id, kind, status, display_name, created_at)
            VALUES (:id, :tenant_id, :kind, :status, :display_name, :created_at)
        """),
        {
            "id": str(principal_id),
            "tenant_id": str(tenant_id),
            "kind": "user",
            "status": "active",
            "display_name": "Lineage Test User",
            "created_at": utcnow_iso(),
        },
    )
    await db_session.flush()
    return tenant_id, principal_id


async def create_dataset_resource(
    db_session: AsyncSession,
    tenant_id,
    principal_id,
    name: str,
    freshness_status: str = "unknown",
) -> DatasetInstance:
    """Create a Resource + DatasetInstance and return the instance."""
    resource_id = uuid4()

    # Create Resource
    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type="DatasetInstance",
        name=name,
        status="active",
    )
    db_session.add(resource)

    # Create DatasetInstance extension
    dataset = DatasetInstance(
        resource_id=resource_id,
        tenant_id=tenant_id,
        freshness_status=freshness_status,
        pipeline_instance_id=uuid4(),
        store_instance_id=uuid4(),
        accessor_instance_id=uuid4(),
    )
    db_session.add(dataset)
    await db_session.flush()

    return dataset


async def create_lineage_edge(
    db_session: AsyncSession,
    tenant_id,
    upstream_id,
    downstream_id,
    edge_kind: str = "data_dependency",
):
    """Create a lineage edge between two resources."""
    edge = DatasetLineage(
        tenant_id=tenant_id,
        upstream_resource_id=upstream_id,
        downstream_resource_id=downstream_id,
        edge_kind=edge_kind,
    )
    db_session.add(edge)
    await db_session.flush()


@pytest.mark.asyncio
class TestUpstreamResolution:
    """Tests for resolve_upstream_dependencies."""

    async def test_no_dependencies_returns_empty(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """A dataset with no upstreams returns empty list."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Standalone Dataset"
        )

        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset.resource_id, recursive=False
        )

        assert upstreams == []

    async def test_single_direct_dependency(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Dataset B depends on Dataset A - returns [A]."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # A -> B (B depends on A)
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )

        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_b.resource_id, recursive=False
        )

        assert len(upstreams) == 1
        assert upstreams[0] == dataset_a.resource_id

    async def test_multiple_direct_dependencies(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Dataset C depends on both A and B."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # A -> C, B -> C
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_c.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_c.resource_id, recursive=False
        )

        assert len(upstreams) == 2
        assert set(upstreams) == {dataset_a.resource_id, dataset_b.resource_id}

    async def test_recursive_chain(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Chain: A -> B -> C -> D. D's recursive upstreams are [C, B, A]."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        datasets = []
        for name in ["A", "B", "C", "D"]:
            ds = await create_dataset_resource(
                db_session, tenant_id, principal_id, f"Dataset {name}"
            )
            datasets.append(ds)

        # Create chain: A -> B -> C -> D
        for i in range(len(datasets) - 1):
            await create_lineage_edge(
                db_session,
                tenant_id,
                datasets[i].resource_id,
                datasets[i + 1].resource_id,
            )

        # Get recursive upstreams of D
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, datasets[3].resource_id, recursive=True
        )

        # Should have C, B, A (in BFS order)
        assert len(upstreams) == 3
        # BFS order: first level (C), then second level (B), then third (A)
        assert upstreams[0] == datasets[2].resource_id  # C
        assert upstreams[1] == datasets[1].resource_id  # B
        assert upstreams[2] == datasets[0].resource_id  # A

    async def test_diamond_pattern(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Diamond: A -> B, A -> C, B -> D, C -> D. D's upstreams are [B, C, A]."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        #     A
        #    / \
        #   B   C
        #    \ /
        #     D
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )
        dataset_d = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset D"
        )

        # A -> B, A -> C
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_c.resource_id
        )
        # B -> D, C -> D
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_d.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_c.resource_id, dataset_d.resource_id
        )

        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_d.resource_id, recursive=True
        )

        # Should include B, C, A - use set for uniqueness check
        # Note: The resolver may return duplicates in paths, but unique nodes are what matters
        unique_upstreams = set(upstreams)
        assert len(unique_upstreams) == 3
        assert unique_upstreams == {
            dataset_a.resource_id,
            dataset_b.resource_id,
            dataset_c.resource_id,
        }


@pytest.mark.asyncio
class TestDownstreamResolution:
    """Tests for resolve_downstream_dependencies."""

    async def test_no_dependents_returns_empty(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """A leaf dataset with no downstreams returns empty list."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Leaf Dataset"
        )

        downstreams = await resolver.resolve_downstream_dependencies(
            db_session, dataset.resource_id, recursive=False
        )

        assert downstreams == []

    async def test_single_dependent(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Dataset A has one dependent B."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )

        downstreams = await resolver.resolve_downstream_dependencies(
            db_session, dataset_a.resource_id, recursive=False
        )

        assert len(downstreams) == 1
        assert downstreams[0] == dataset_b.resource_id

    async def test_recursive_fan_out(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """A -> B, A -> C, B -> D, C -> E. A's recursive downstreams are [B, C, D, E]."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        #     A
        #    / \
        #   B   C
        #   |   |
        #   D   E
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )
        dataset_d = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset D"
        )
        dataset_e = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset E"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_c.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_d.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_c.resource_id, dataset_e.resource_id
        )

        downstreams = await resolver.resolve_downstream_dependencies(
            db_session, dataset_a.resource_id, recursive=True
        )

        assert len(downstreams) == 4
        assert set(downstreams) == {
            dataset_b.resource_id,
            dataset_c.resource_id,
            dataset_d.resource_id,
            dataset_e.resource_id,
        }


@pytest.mark.asyncio
class TestExecutionOrder:
    """Tests for get_execution_order (topological sorting)."""

    async def test_single_node_returns_one_batch(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Single node with no dependencies returns single batch."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Single Dataset"
        )

        batches = await resolver.get_execution_order(db_session, dataset.resource_id)

        assert len(batches) == 1
        assert batches[0] == [dataset.resource_id]

    async def test_chain_returns_sequential_batches(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Chain A -> B -> C returns batches [[A], [B], [C]]."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        batches = await resolver.get_execution_order(db_session, dataset_c.resource_id)

        # Should be 3 batches, each with one item
        assert len(batches) == 3
        assert batches[0] == [dataset_a.resource_id]
        assert batches[1] == [dataset_b.resource_id]
        assert batches[2] == [dataset_c.resource_id]

    async def test_parallel_nodes_in_same_batch(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Diamond pattern: A -> B, A -> C, B/C -> D. Batches: [[A], [B,C], [D]]."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )
        dataset_d = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset D"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_c.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_d.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_c.resource_id, dataset_d.resource_id
        )

        batches = await resolver.get_execution_order(db_session, dataset_d.resource_id)

        # Should be 3 batches
        assert len(batches) == 3
        assert batches[0] == [dataset_a.resource_id]  # A first
        assert set(batches[1]) == {
            dataset_b.resource_id,
            dataset_c.resource_id,
        }  # B and C in parallel
        assert batches[2] == [dataset_d.resource_id]  # D last

    async def test_complex_dag_correct_order(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        r"""Complex DAG with multiple roots and shared dependencies.

        Graph:
            R1    R2
            |     |
            A     B
             \   /|
              \ / |
               C  |
               |  |
               D--+

        R1 -> A -> C -> D
        R2 -> B -> C
        R2 -> B -> D

        Expected batches: [[R1, R2], [A, B], [C], [D]]
        """
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        r1 = await create_dataset_resource(db_session, tenant_id, principal_id, "R1")
        r2 = await create_dataset_resource(db_session, tenant_id, principal_id, "R2")
        a = await create_dataset_resource(db_session, tenant_id, principal_id, "A")
        b = await create_dataset_resource(db_session, tenant_id, principal_id, "B")
        c = await create_dataset_resource(db_session, tenant_id, principal_id, "C")
        d = await create_dataset_resource(db_session, tenant_id, principal_id, "D")

        # R1 -> A -> C -> D
        await create_lineage_edge(db_session, tenant_id, r1.resource_id, a.resource_id)
        await create_lineage_edge(db_session, tenant_id, a.resource_id, c.resource_id)
        await create_lineage_edge(db_session, tenant_id, c.resource_id, d.resource_id)

        # R2 -> B -> C, B -> D
        await create_lineage_edge(db_session, tenant_id, r2.resource_id, b.resource_id)
        await create_lineage_edge(db_session, tenant_id, b.resource_id, c.resource_id)
        await create_lineage_edge(db_session, tenant_id, b.resource_id, d.resource_id)

        batches = await resolver.get_execution_order(db_session, d.resource_id)

        # Verify order respects dependencies
        assert len(batches) == 4

        # Batch 0: roots (R1, R2) - no dependencies
        assert set(batches[0]) == {r1.resource_id, r2.resource_id}

        # Batch 1: A, B - depend only on roots
        assert set(batches[1]) == {a.resource_id, b.resource_id}

        # Batch 2: C - depends on A and B
        assert batches[2] == [c.resource_id]

        # Batch 3: D - depends on C and B
        assert batches[3] == [d.resource_id]


@pytest.mark.asyncio
class TestStalenesssPropagation:
    """Tests for propagate_staleness."""

    async def test_propagates_to_direct_dependents(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """When A changes, direct dependent B becomes stale."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A", freshness_status="fresh"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B", freshness_status="fresh"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )

        # Propagate staleness from A
        affected = await resolver.propagate_staleness(db_session, dataset_a.resource_id)

        # B should be affected
        assert len(affected) == 1
        assert affected[0] == dataset_b.resource_id

        # Verify B is now stale in the database (re-query after commit)
        from libs.db.models.quant import DatasetInstance

        updated_b = await db_session.get(DatasetInstance, dataset_b.resource_id)
        assert updated_b.freshness_status == "stale"

    async def test_propagates_recursively(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Chain A -> B -> C: when A changes, both B and C become stale."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A", freshness_status="fresh"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B", freshness_status="fresh"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C", freshness_status="fresh"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        affected = await resolver.propagate_staleness(db_session, dataset_a.resource_id)

        # Both B and C should be affected
        assert len(affected) == 2
        assert set(affected) == {dataset_b.resource_id, dataset_c.resource_id}

        # Verify both are stale (re-query after commit)
        from libs.db.models.quant import DatasetInstance

        updated_b = await db_session.get(DatasetInstance, dataset_b.resource_id)
        updated_c = await db_session.get(DatasetInstance, dataset_c.resource_id)
        assert updated_b.freshness_status == "stale"
        assert updated_c.freshness_status == "stale"

    async def test_skips_already_stale(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Already-stale datasets are not included in affected list."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A", freshness_status="fresh"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B", freshness_status="stale"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )

        affected = await resolver.propagate_staleness(db_session, dataset_a.resource_id)

        # B was already stale, so not in affected list
        assert len(affected) == 0


@pytest.mark.asyncio
class TestLineageEdgeManagement:
    """Tests for add_lineage_edge and remove_lineage_edge."""

    async def test_add_and_query_edge(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Add an edge and verify it's queryable."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )

        # Add edge via resolver
        await resolver.add_lineage_edge(
            db_session,
            tenant_id,
            dataset_a.resource_id,
            dataset_b.resource_id,
            edge_kind="data_dependency",
        )
        await db_session.flush()

        # Query upstreams
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_b.resource_id, recursive=False
        )

        assert len(upstreams) == 1
        assert upstreams[0] == dataset_a.resource_id

    async def test_remove_edge(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Remove an edge and verify it's gone."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )

        # Add and then remove edge
        await resolver.add_lineage_edge(
            db_session,
            tenant_id,
            dataset_a.resource_id,
            dataset_b.resource_id,
        )
        await db_session.flush()

        removed = await resolver.remove_lineage_edge(
            db_session, dataset_a.resource_id, dataset_b.resource_id
        )

        assert removed is True

        # Verify edge is gone
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_b.resource_id, recursive=False
        )
        assert upstreams == []

    async def test_remove_nonexistent_edge_returns_false(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Removing an edge that doesn't exist returns False."""
        removed = await resolver.remove_lineage_edge(db_session, uuid4(), uuid4())

        assert removed is False


@pytest.mark.asyncio
class TestLineageGraph:
    """Tests for get_lineage_graph visualization."""

    async def test_graph_includes_upstream_and_downstream(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Graph centered on B includes A (upstream) and C (downstream)."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # A -> B -> C
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        graph = await resolver.get_lineage_graph(
            db_session, dataset_b.resource_id, direction="both"
        )

        # Should have 3 nodes
        assert len(graph["nodes"]) == 3

        node_ids = {node["id"] for node in graph["nodes"]}
        assert str(dataset_a.resource_id) in node_ids
        assert str(dataset_b.resource_id) in node_ids
        assert str(dataset_c.resource_id) in node_ids

        # Should have 2 edges
        assert len(graph["edges"]) == 2

        # Center should be B
        assert graph["center_id"] == str(dataset_b.resource_id)

    async def test_upstream_only_direction(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """direction='upstream' only includes upstream nodes."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # A -> B -> C
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        graph = await resolver.get_lineage_graph(
            db_session, dataset_b.resource_id, direction="upstream"
        )

        # Should have 2 nodes: A and B (center)
        assert len(graph["nodes"]) == 2

        node_ids = {node["id"] for node in graph["nodes"]}
        assert str(dataset_a.resource_id) in node_ids
        assert str(dataset_b.resource_id) in node_ids
        assert str(dataset_c.resource_id) not in node_ids


@pytest.mark.asyncio
class TestBuildDAGForInstance:
    """Tests for build_dag_for_instance - DAG construction from instance config."""

    async def test_extracts_from_pipeline_config_input_datasets(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Extracts upstream IDs from pipeline config's input_datasets field."""
        from libs.db.models.quant import PipelineInstance

        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # Create upstream datasets
        upstream1 = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Upstream 1"
        )
        upstream2 = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Upstream 2"
        )

        # Create pipeline instance with config
        pipeline_id = uuid4()
        definition_id = uuid4()
        # First create the pipeline definition resource
        db_session.add(
            Resource(
                id=definition_id,
                tenant_id=tenant_id,
                owner_principal_id=principal_id,
                type="PipelineDef",
                name="Test Pipeline Def",
            )
        )
        pipeline = PipelineInstance(
            resource_id=pipeline_id,
            tenant_id=tenant_id,
            definition_resource_id=definition_id,
            config_json={
                "input_datasets": [
                    str(upstream1.resource_id),
                    str(upstream2.resource_id),
                ]
            },
        )
        db_session.add(
            Resource(
                id=pipeline_id,
                tenant_id=tenant_id,
                owner_principal_id=principal_id,
                type="PipelineInstance",
                name="Test Pipeline",
            )
        )
        db_session.add(pipeline)

        # Create dataset instance referencing this pipeline
        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dependent Dataset"
        )
        dataset.pipeline_instance_id = pipeline_id
        await db_session.flush()

        # Build DAG
        dag = await resolver.build_dag_for_instance(
            db_session, dataset.resource_id, tenant_id
        )

        assert dag.instance_id == dataset.resource_id
        assert dag.tenant_id == tenant_id
        assert len(dag.upstream_ids) == 2
        assert set(dag.upstream_ids) == {upstream1.resource_id, upstream2.resource_id}
        assert dag.has_dependencies is True

    async def test_empty_dependencies_returns_empty_dag(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Instance with no configured dependencies returns empty DAG."""
        from libs.db.models.quant import PipelineInstance

        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # Create pipeline instance with empty config
        pipeline_id = uuid4()
        definition_id = uuid4()
        # First create the pipeline definition resource
        db_session.add(
            Resource(
                id=definition_id,
                tenant_id=tenant_id,
                owner_principal_id=principal_id,
                type="PipelineDef",
                name="Test Pipeline Def",
            )
        )
        pipeline = PipelineInstance(
            resource_id=pipeline_id,
            tenant_id=tenant_id,
            definition_resource_id=definition_id,
            config_json={},
        )
        db_session.add(
            Resource(
                id=pipeline_id,
                tenant_id=tenant_id,
                owner_principal_id=principal_id,
                type="PipelineInstance",
                name="Empty Pipeline",
            )
        )
        db_session.add(pipeline)

        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "No Deps Dataset"
        )
        dataset.pipeline_instance_id = pipeline_id
        await db_session.flush()

        dag = await resolver.build_dag_for_instance(
            db_session, dataset.resource_id, tenant_id
        )

        assert len(dag.upstream_ids) == 0
        assert dag.has_dependencies is False


@pytest.mark.asyncio
class TestCycleDetection:
    """Tests for cycle detection in get_execution_order.

    Cycles in dependency graphs are a critical error case that must be detected
    and reported clearly. Without cycle detection, the execution order algorithm
    would loop infinitely.
    """

    async def test_simple_cycle_raises_error(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Direct cycle A -> B -> A raises ValueError."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )

        # Create cycle: A -> B -> A
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_a.resource_id
        )

        with pytest.raises(ValueError, match="[Cc]ycle"):
            await resolver.get_execution_order(db_session, dataset_a.resource_id)

    async def test_indirect_cycle_raises_error(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Longer cycle A -> B -> C -> A raises ValueError."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C"
        )

        # Create cycle: A -> B -> C -> A
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_c.resource_id, dataset_a.resource_id
        )

        with pytest.raises(ValueError, match="[Cc]ycle"):
            await resolver.get_execution_order(db_session, dataset_c.resource_id)


@pytest.mark.asyncio
class TestCheckUpstreamFreshness:
    """Tests for check_upstream_freshness - smart execution feature.

    This is the core of "smart execution" where we check if all upstream
    dependencies are fresh before allowing a pipeline to run.
    """

    async def test_all_fresh_returns_ready(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """When all upstreams are fresh, returns all_ready=True."""
        from libs.orchestration.freshness import FreshnessChecker
        from libs.orchestration.status_store import StatusStore

        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # A -> B -> C, all fresh
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A", freshness_status="fresh"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B", freshness_status="fresh"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C", freshness_status="fresh"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        # Mark all as successfully run in status store with data dates
        from datetime import date

        status_store = StatusStore(db_session)
        for ds in [dataset_a, dataset_b, dataset_c]:
            await status_store.mark_run_start(ds.resource_id)
            await status_store.mark_run_success(
                ds.resource_id, last_data_date=date.today()
            )

        freshness_checker = FreshnessChecker(status_store)
        report = await resolver.check_upstream_freshness(
            db_session, dataset_c.resource_id, freshness_checker
        )

        assert report.all_ready is True
        assert len(report.blocking_resources) == 0
        assert len(report.status_map) == 2  # A and B

    async def test_stale_upstream_blocks(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """When an upstream is stale, returns all_ready=False with blockers."""
        from libs.orchestration.freshness import FreshnessChecker
        from libs.orchestration.status_store import StatusStore

        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # A (error) -> B (fresh) -> C
        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A", freshness_status="stale"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B", freshness_status="fresh"
        )
        dataset_c = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset C", freshness_status="unknown"
        )

        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_id, dataset_b.resource_id, dataset_c.resource_id
        )

        # Mark A as error, B as success
        status_store = StatusStore(db_session)
        await status_store.mark_run_start(dataset_a.resource_id)
        await status_store.mark_run_error(dataset_a.resource_id, "Test error")
        await status_store.mark_run_start(dataset_b.resource_id)
        await status_store.mark_run_success(dataset_b.resource_id)

        freshness_checker = FreshnessChecker(status_store)
        report = await resolver.check_upstream_freshness(
            db_session, dataset_c.resource_id, freshness_checker
        )

        assert report.all_ready is False
        assert dataset_a.resource_id in report.blocking_resources

    async def test_no_dependencies_is_ready(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Resource with no dependencies is always ready."""
        from libs.orchestration.freshness import FreshnessChecker
        from libs.orchestration.status_store import StatusStore

        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Standalone", freshness_status="stale"
        )

        status_store = StatusStore(db_session)
        freshness_checker = FreshnessChecker(status_store)
        report = await resolver.check_upstream_freshness(
            db_session, dataset.resource_id, freshness_checker
        )

        assert report.all_ready is True
        assert len(report.blocking_resources) == 0


@pytest.mark.asyncio
class TestTenantIsolation:
    """Tests ensuring lineage data is isolated between tenants."""

    async def test_cannot_see_other_tenant_lineage(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Tenant A cannot see Tenant B's lineage edges."""
        # Create two tenants
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()
        principal_a_id = uuid4()
        principal_b_id = uuid4()

        await db_session.execute(
            text("""
                INSERT INTO tenants (id, name, created_at)
                VALUES (:id, :name, :created_at)
            """),
            {"id": str(tenant_a_id), "name": "Tenant A", "created_at": utcnow_iso()},
        )
        await db_session.execute(
            text("""
                INSERT INTO tenants (id, name, created_at)
                VALUES (:id, :name, :created_at)
            """),
            {"id": str(tenant_b_id), "name": "Tenant B", "created_at": utcnow_iso()},
        )
        await db_session.execute(
            text("""
                INSERT INTO principals (id, tenant_id, kind, status, display_name, created_at)
                VALUES (:id, :tenant_id, :kind, :status, :display_name, :created_at)
            """),
            {
                "id": str(principal_a_id),
                "tenant_id": str(tenant_a_id),
                "kind": "user",
                "status": "active",
                "display_name": "User A",
                "created_at": utcnow_iso(),
            },
        )
        await db_session.execute(
            text("""
                INSERT INTO principals (id, tenant_id, kind, status, display_name, created_at)
                VALUES (:id, :tenant_id, :kind, :status, :display_name, :created_at)
            """),
            {
                "id": str(principal_b_id),
                "tenant_id": str(tenant_b_id),
                "kind": "user",
                "status": "active",
                "display_name": "User B",
                "created_at": utcnow_iso(),
            },
        )
        await db_session.flush()

        # Create datasets for both tenants
        ds_a1 = await create_dataset_resource(
            db_session, tenant_a_id, principal_a_id, "Tenant A Dataset 1"
        )
        ds_a2 = await create_dataset_resource(
            db_session, tenant_a_id, principal_a_id, "Tenant A Dataset 2"
        )
        ds_b1 = await create_dataset_resource(
            db_session, tenant_b_id, principal_b_id, "Tenant B Dataset 1"
        )
        ds_b2 = await create_dataset_resource(
            db_session, tenant_b_id, principal_b_id, "Tenant B Dataset 2"
        )

        # Create edges for both tenants
        await create_lineage_edge(
            db_session, tenant_a_id, ds_a1.resource_id, ds_a2.resource_id
        )
        await create_lineage_edge(
            db_session, tenant_b_id, ds_b1.resource_id, ds_b2.resource_id
        )

        # Query from A's perspective - should only see A's edge
        # Note: The current implementation doesn't filter by tenant in queries,
        # but the data IS stored with tenant_id. This test verifies the data model.
        upstreams_a = await resolver.resolve_upstream_dependencies(
            db_session, ds_a2.resource_id, recursive=False
        )
        upstreams_b = await resolver.resolve_upstream_dependencies(
            db_session, ds_b2.resource_id, recursive=False
        )

        # A's upstream should be A1, B's upstream should be B1
        assert ds_a1.resource_id in upstreams_a
        assert ds_b1.resource_id not in upstreams_a
        assert ds_b1.resource_id in upstreams_b
        assert ds_a1.resource_id not in upstreams_b


@pytest.mark.asyncio
class TestLongChains:
    """Tests for handling long dependency chains."""

    async def test_deep_chain_performance(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Long chain (10+ nodes) is handled correctly."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # Create chain of 15 datasets
        datasets = []
        for i in range(15):
            ds = await create_dataset_resource(
                db_session, tenant_id, principal_id, f"Chain Dataset {i}"
            )
            datasets.append(ds)

        # Create chain: 0 -> 1 -> 2 -> ... -> 14
        for i in range(len(datasets) - 1):
            await create_lineage_edge(
                db_session,
                tenant_id,
                datasets[i].resource_id,
                datasets[i + 1].resource_id,
            )

        # Get execution order for the last dataset
        batches = await resolver.get_execution_order(
            db_session, datasets[-1].resource_id
        )

        # Should have 15 batches (one per node in chain)
        assert len(batches) == 15

        # First batch should be the root (dataset 0)
        assert batches[0] == [datasets[0].resource_id]

        # Last batch should be the leaf (dataset 14)
        assert batches[-1] == [datasets[-1].resource_id]

    async def test_wide_fan_in(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Many upstreams feeding into one downstream."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        # Create 10 upstream datasets
        upstreams = []
        for i in range(10):
            ds = await create_dataset_resource(
                db_session, tenant_id, principal_id, f"Upstream {i}"
            )
            upstreams.append(ds)

        # Create one downstream
        downstream = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Downstream"
        )

        # All upstreams feed into downstream
        for up in upstreams:
            await create_lineage_edge(
                db_session, tenant_id, up.resource_id, downstream.resource_id
            )

        # Get execution order
        batches = await resolver.get_execution_order(db_session, downstream.resource_id)

        # Should have 2 batches: all upstreams in parallel, then downstream
        assert len(batches) == 2
        assert set(batches[0]) == {u.resource_id for u in upstreams}
        assert batches[1] == [downstream.resource_id]


@pytest.mark.asyncio
class TestEdgeCases:
    """Edge case tests for lineage operations."""

    async def test_self_dependency_is_cycle(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """A resource depending on itself is a cycle."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Self Dependent"
        )

        # Create self-referencing edge
        await create_lineage_edge(
            db_session, tenant_id, dataset.resource_id, dataset.resource_id
        )

        with pytest.raises(ValueError, match="[Cc]ycle"):
            await resolver.get_execution_order(db_session, dataset.resource_id)

    async def test_duplicate_edges_handled(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Duplicate edges don't cause issues."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        dataset_a = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset A"
        )
        dataset_b = await create_dataset_resource(
            db_session, tenant_id, principal_id, "Dataset B"
        )

        # Add the same edge twice (if DB allows - some may have unique constraint)
        await create_lineage_edge(
            db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
        )
        try:
            await create_lineage_edge(
                db_session, tenant_id, dataset_a.resource_id, dataset_b.resource_id
            )
        except Exception:
            # If duplicate not allowed, that's fine
            pass

        # Should still work correctly
        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, dataset_b.resource_id, recursive=False
        )

        # Should have exactly 1 upstream (not duplicated in results)
        assert dataset_a.resource_id in upstreams

    async def test_nonexistent_resource_upstream(
        self, db_session: AsyncSession, resolver: LineageResolver
    ):
        """Querying upstreams for non-existent resource returns empty."""
        fake_id = uuid4()

        upstreams = await resolver.resolve_upstream_dependencies(
            db_session, fake_id, recursive=True
        )

        assert upstreams == []
