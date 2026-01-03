"""Tests for LineageResolver logic.

Tests the graph traversal and execution order calculation logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from libs.orchestration.lineage import LineageResolver


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def resolver():
    """LineageResolver instance."""
    return LineageResolver()


@pytest.mark.asyncio
class TestLineageResolverLogic:
    """Tests for LineageResolver."""

    async def test_resolve_upstream_dependency_direct(self, resolver, mock_session):
        """Test resolving direct upstream dependencies."""
        resource_id = uuid4()
        upstream_id = uuid4()

        # Mock result
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [upstream_id]
        mock_session.execute.return_value = mock_result

        result = await resolver.resolve_upstream_dependencies(
            mock_session, resource_id, recursive=False
        )

        assert len(result) == 1
        assert result[0] == upstream_id

        # Verify query structure (simplified check)
        mock_session.execute.assert_called_once()
        # Should filter by downstream_resource_id == resource_id

    async def test_resolve_upstream_recursive(self, resolver, mock_session):
        """Test resolving upstream dependencies recursively (BFS)."""
        # Graph: C -> B -> A (A depends on B, B depends on C)
        a = uuid4()
        b = uuid4()
        c = uuid4()

        # Chain of mocks for sequential calls
        # 1. Get upstreams of A -> [B]
        # 2. Get upstreams of B -> [C]
        # 3. Get upstreams of C -> []

        results = [
            [b],  # call for A
            [c],  # call for B
            [],  # call for C
        ]

        mock_result_objects = []
        for res_list in results:
            m = MagicMock()
            m.scalars().all.return_value = res_list
            mock_result_objects.append(m)

        mock_session.execute.side_effect = mock_result_objects

        ordered = await resolver.resolve_upstream_dependencies(
            mock_session, a, recursive=True
        )

        # Order should be [B, C] (BFS order)
        assert len(ordered) == 2
        assert ordered[0] == b
        assert ordered[1] == c
        assert mock_session.execute.call_count == 3

    async def test_get_execution_order(self, resolver, mock_session):
        """Test topological sort / execution batches."""
        # Graph: Root -> A, Root -> B, A -> C, B -> C
        # Batches: [Root], [A, B], [C]
        root = uuid4()
        a = uuid4()
        b = uuid4()
        c = uuid4()

        # 1. Mock resolve_upstream_dependencies (recursive) to return all nodes
        # This is called first to build the subgraph
        with patch.object(resolver, "resolve_upstream_dependencies") as mock_resolve:
            mock_resolve.return_value = [
                root,
                a,
                b,
            ]  # Mock implementation returns flat list

            # 2. Mock DB query for edges
            # Should return all edges within the subgraph
            edges = [
                # upstream, downstream
                (root, a),
                (root, b),
                (a, c),
                (b, c),
            ]

            mock_result = MagicMock()
            mock_result.all.return_value = edges
            mock_session.execute.return_value = mock_result

            batches = await resolver.get_execution_order(
                mock_session,
                c,  # Getting execution order for C's lineage
            )

            # We actually called get_execution_order(..., c) but the method naming
            # implies execution order *from* a root.
            # Looking at implementation:
            # It calls resolve_upstream_dependencies(root_id).
            # Then gets edges where downstream is in that set.
            # Then Kahn's algorithm.

            # If we pass 'c' as root_id, it finds ustreams {a, b, root}.
            # Edges: root->a, root->b, a->c, b->c.
            # In-degrees: root:0, a:1, b:1, c:2.
            # Batch 1: [root] -> removes edges from root -> a:0, b:0.
            # Batch 2: [a, b] -> removes edges from a,b -> c:0.
            # Batch 3: [c].

            assert len(batches) == 3
            assert batches[0] == [root]
            assert set(batches[1]) == {a, b}
            assert batches[2] == [c]
