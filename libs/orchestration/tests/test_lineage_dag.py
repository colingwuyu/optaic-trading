"""Tests for Lineage DAG building and subscription creation.

Phase 2.8.1: Tests for lineage setup at flow creation time.
"""

from uuid import uuid4


from libs.orchestration import LineageDAG, LineageResolver


class TestLineageDAG:
    """Tests for LineageDAG dataclass."""

    def test_create_empty(self) -> None:
        """Test creating an empty DAG."""
        dag = LineageDAG(
            instance_id=uuid4(),
            tenant_id=uuid4(),
            upstream_ids=[],
        )
        assert dag.has_dependencies is False

    def test_create_with_upstreams(self) -> None:
        """Test creating a DAG with upstream dependencies."""
        upstream_id = uuid4()
        dag = LineageDAG(
            instance_id=uuid4(),
            tenant_id=uuid4(),
            upstream_ids=[upstream_id],
        )
        assert dag.has_dependencies is True
        assert len(dag.upstream_ids) == 1
        assert dag.upstream_ids[0] == upstream_id

    def test_has_dependencies_property(self) -> None:
        """Test the has_dependencies property."""
        instance_id = uuid4()
        tenant_id = uuid4()

        # Empty
        dag_empty = LineageDAG(instance_id, tenant_id, [])
        assert dag_empty.has_dependencies is False

        # With one
        dag_one = LineageDAG(instance_id, tenant_id, [uuid4()])
        assert dag_one.has_dependencies is True

        # With multiple
        dag_many = LineageDAG(instance_id, tenant_id, [uuid4(), uuid4(), uuid4()])
        assert dag_many.has_dependencies is True


class TestLineageResolverExtractUpstream:
    """Tests for extracting upstream dependencies from pipeline config."""

    def test_extract_from_input_datasets(self) -> None:
        """Test extracting from input_datasets list."""
        resolver = LineageResolver()
        dataset_id_1 = uuid4()
        dataset_id_2 = uuid4()

        config = {"input_datasets": [str(dataset_id_1), str(dataset_id_2)]}
        upstreams = resolver._extract_upstream_from_pipeline_config(config)

        assert len(upstreams) == 2
        assert dataset_id_1 in upstreams
        assert dataset_id_2 in upstreams

    def test_extract_from_upstream_datasets(self) -> None:
        """Test extracting from upstream_datasets list."""
        resolver = LineageResolver()
        dataset_id = uuid4()

        config = {"upstream_datasets": [str(dataset_id)]}
        upstreams = resolver._extract_upstream_from_pipeline_config(config)

        assert len(upstreams) == 1
        assert dataset_id in upstreams

    def test_extract_from_expression_inputs(self) -> None:
        """Test extracting from expression_inputs dict."""
        resolver = LineageResolver()
        dataset_id_1 = uuid4()
        dataset_id_2 = uuid4()

        config = {
            "expression_inputs": {
                "prices": str(dataset_id_1),
                "volumes": str(dataset_id_2),
            }
        }
        upstreams = resolver._extract_upstream_from_pipeline_config(config)

        assert len(upstreams) == 2
        assert dataset_id_1 in upstreams
        assert dataset_id_2 in upstreams

    def test_extract_from_sources(self) -> None:
        """Test extracting from sources list with dataset_id."""
        resolver = LineageResolver()
        dataset_id = uuid4()

        config = {
            "sources": [
                {"name": "source1", "dataset_id": str(dataset_id)},
                {"name": "source2", "type": "file"},  # No dataset_id
            ]
        }
        upstreams = resolver._extract_upstream_from_pipeline_config(config)

        assert len(upstreams) == 1
        assert dataset_id in upstreams

    def test_extract_from_multiple_patterns(self) -> None:
        """Test extracting from multiple patterns combined."""
        resolver = LineageResolver()
        id1 = uuid4()
        id2 = uuid4()
        id3 = uuid4()

        config = {
            "input_datasets": [str(id1)],
            "expression_inputs": {"alias": str(id2)},
            "sources": [{"dataset_id": str(id3)}],
        }
        upstreams = resolver._extract_upstream_from_pipeline_config(config)

        assert len(upstreams) == 3
        assert id1 in upstreams
        assert id2 in upstreams
        assert id3 in upstreams

    def test_extract_with_invalid_uuids(self) -> None:
        """Test that invalid UUIDs are skipped."""
        resolver = LineageResolver()
        valid_id = uuid4()

        config = {
            "input_datasets": [
                str(valid_id),
                "not-a-uuid",
                "",
                None,
            ]
        }
        upstreams = resolver._extract_upstream_from_pipeline_config(config)

        assert len(upstreams) == 1
        assert valid_id in upstreams

    def test_extract_empty_config(self) -> None:
        """Test extracting from empty config."""
        resolver = LineageResolver()
        upstreams = resolver._extract_upstream_from_pipeline_config({})
        assert len(upstreams) == 0


class TestLineageResolverUpstreamStatus:
    """Tests for upstream status tracking methods."""

    def test_lineage_resolver_can_be_created(self) -> None:
        """Test that LineageResolver can be instantiated."""
        resolver = LineageResolver()
        assert resolver is not None


# NOTE: Integration tests for LineageResolver with database are in:
# apps/api/tests/test_lineage_comprehensive.py
# Those tests use the multi-account sandbox with real db_session fixtures.
#
# Tests that were removed (just had `pass`):
# - test_check_all_upstreams_ready_no_deps -> see TestUpstreamStatusTracking in test_lineage_comprehensive.py
# - test_build_dag_for_nonexistent_instance -> needs real db fixtures, test in integration suite
