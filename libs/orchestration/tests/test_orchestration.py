"""Tests for orchestration package.

Tests for:
- DependencyGraph and build_graph()
- LocalOrchestrator
- OrchestratorAdapter interface
- StatusStore
- RunExecutionService
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from libs.orchestration.adapter import OrchestratorAdapter, RunStatus, SubmitResult
from libs.orchestration.dag import DependencyGraph, GraphEdge, GraphNode, NodeData
from libs.orchestration.freshness import (
    DatasetStatus,
    FreshnessReport,
    UpdateFrequency,
)
from libs.orchestration.lineage import (
    LineageFreshnessReport,
    LineageResolver,
    UpstreamNotReadyError,
)
from libs.orchestration.local import LocalOrchestrator, LocalRunState
from libs.orchestration.status_store import DatasetStatusRecord


class TestDependencyGraph:
    """Tests for DependencyGraph."""

    def test_create_empty_graph(self) -> None:
        """Test creating an empty graph."""
        graph = DependencyGraph()
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_add_node(self) -> None:
        """Test adding a node to the graph."""
        graph = DependencyGraph()
        node_id = uuid4()

        graph.add_node(
            resource_id=node_id,
            name="Test Dataset",
            resource_type="DatasetInstance",
            code_ref="ExpressionPipeline",
            status="fresh",
        )

        assert len(graph.nodes) == 1
        assert str(node_id) in graph.nodes

        node = graph.nodes[str(node_id)]
        assert node.label == "Test Dataset"
        assert node.type == "DatasetInstance"
        assert node.data.code_ref == "ExpressionPipeline"
        assert node.data.status == "fresh"

    def test_add_duplicate_node(self) -> None:
        """Test adding same node twice doesn't duplicate."""
        graph = DependencyGraph()
        node_id = uuid4()

        graph.add_node(resource_id=node_id, name="Test", resource_type="Dataset")
        graph.add_node(
            resource_id=node_id, name="Test Changed", resource_type="Dataset"
        )

        assert len(graph.nodes) == 1
        # First add wins
        assert graph.nodes[str(node_id)].label == "Test"

    def test_add_edge(self) -> None:
        """Test adding an edge between nodes."""
        graph = DependencyGraph()
        upstream_id = uuid4()
        downstream_id = uuid4()

        graph.add_node(
            resource_id=upstream_id, name="Upstream", resource_type="Dataset"
        )
        graph.add_node(
            resource_id=downstream_id, name="Downstream", resource_type="Signal"
        )
        graph.add_edge(upstream_id, downstream_id)

        assert len(graph.edges) == 1
        assert graph.edges[0].source == str(upstream_id)
        assert graph.edges[0].target == str(downstream_id)

    def test_add_edge_missing_node_raises(self) -> None:
        """Test adding edge with missing node raises error."""
        graph = DependencyGraph()
        node_id = uuid4()
        missing_id = uuid4()

        graph.add_node(resource_id=node_id, name="Test", resource_type="Dataset")

        with pytest.raises(ValueError, match="not in graph"):
            graph.add_edge(node_id, missing_id)

    def test_get_upstream(self) -> None:
        """Test getting upstream dependencies."""
        graph = DependencyGraph()
        upstream1 = uuid4()
        upstream2 = uuid4()
        downstream = uuid4()

        graph.add_node(resource_id=upstream1, name="Up1", resource_type="Dataset")
        graph.add_node(resource_id=upstream2, name="Up2", resource_type="Dataset")
        graph.add_node(resource_id=downstream, name="Down", resource_type="Signal")

        graph.add_edge(upstream1, downstream)
        graph.add_edge(upstream2, downstream)

        upstream = graph.get_upstream(downstream)
        assert len(upstream) == 2
        upstream_ids = {str(u.data.resource_id) for u in upstream}
        assert str(upstream1) in upstream_ids
        assert str(upstream2) in upstream_ids

    def test_get_downstream(self) -> None:
        """Test getting downstream dependents."""
        graph = DependencyGraph()
        upstream = uuid4()
        downstream1 = uuid4()
        downstream2 = uuid4()

        graph.add_node(resource_id=upstream, name="Up", resource_type="Dataset")
        graph.add_node(resource_id=downstream1, name="Down1", resource_type="Signal")
        graph.add_node(resource_id=downstream2, name="Down2", resource_type="Signal")

        graph.add_edge(upstream, downstream1)
        graph.add_edge(upstream, downstream2)

        downstream = graph.get_downstream(upstream)
        assert len(downstream) == 2

    def test_get_execution_order_linear(self) -> None:
        """Test execution order for linear DAG."""
        graph = DependencyGraph()
        a = uuid4()
        b = uuid4()
        c = uuid4()

        graph.add_node(resource_id=a, name="A", resource_type="Dataset")
        graph.add_node(resource_id=b, name="B", resource_type="Dataset")
        graph.add_node(resource_id=c, name="C", resource_type="Dataset")

        # A -> B -> C
        graph.add_edge(a, b)
        graph.add_edge(b, c)

        batches = graph.get_execution_order()

        # Should have 3 batches (one per node)
        assert len(batches) == 3
        assert str(a) in batches[0]
        assert str(b) in batches[1]
        assert str(c) in batches[2]

    def test_get_execution_order_parallel(self) -> None:
        """Test execution order allows parallel execution."""
        graph = DependencyGraph()
        root = uuid4()
        branch1 = uuid4()
        branch2 = uuid4()
        merge = uuid4()

        graph.add_node(resource_id=root, name="Root", resource_type="Dataset")
        graph.add_node(resource_id=branch1, name="Branch1", resource_type="Dataset")
        graph.add_node(resource_id=branch2, name="Branch2", resource_type="Dataset")
        graph.add_node(resource_id=merge, name="Merge", resource_type="Signal")

        # Root -> Branch1 -> Merge
        # Root -> Branch2 -> Merge
        graph.add_edge(root, branch1)
        graph.add_edge(root, branch2)
        graph.add_edge(branch1, merge)
        graph.add_edge(branch2, merge)

        batches = graph.get_execution_order()

        # Batch 0: Root
        # Batch 1: Branch1, Branch2 (parallel)
        # Batch 2: Merge
        assert len(batches) == 3
        assert str(root) in batches[0]
        assert set([str(branch1), str(branch2)]) == set(batches[1])
        assert str(merge) in batches[2]

    def test_to_dict(self) -> None:
        """Test serializing graph to dict."""
        graph = DependencyGraph()
        a = uuid4()
        b = uuid4()

        graph.add_node(
            resource_id=a, name="A", resource_type="Dataset", code_ref="PipeA"
        )
        graph.add_node(resource_id=b, name="B", resource_type="Signal")
        graph.add_edge(a, b)

        data = graph.to_dict()

        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

        # Check node structure
        node_a = next(n for n in data["nodes"] if n["id"] == str(a))
        assert node_a["label"] == "A"
        assert node_a["type"] == "Dataset"
        assert node_a["code_ref"] == "PipeA"

    def test_from_dict(self) -> None:
        """Test deserializing graph from dict."""
        a_id = str(uuid4())
        b_id = str(uuid4())

        data = {
            "nodes": [
                {
                    "id": a_id,
                    "label": "A",
                    "type": "Dataset",
                    "resource_id": a_id,
                    "code_ref": "PipeA",
                    "config": {},
                    "status": "fresh",
                },
                {
                    "id": b_id,
                    "label": "B",
                    "type": "Signal",
                    "resource_id": b_id,
                    "code_ref": None,
                    "config": {},
                    "status": "stale",
                },
            ],
            "edges": [{"source": a_id, "target": b_id}],
        }

        graph = DependencyGraph.from_dict(data)

        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.nodes[a_id].label == "A"
        assert graph.nodes[b_id].data.status == "stale"

    def test_get_stale_nodes(self) -> None:
        """Test getting nodes with stale status."""
        graph = DependencyGraph()

        graph.add_node(
            resource_id=uuid4(), name="Fresh", resource_type="Dataset", status="fresh"
        )
        graph.add_node(
            resource_id=uuid4(), name="Stale", resource_type="Dataset", status="stale"
        )
        graph.add_node(
            resource_id=uuid4(),
            name="Unknown",
            resource_type="Dataset",
            status="unknown",
        )

        stale = graph.get_stale_nodes()
        assert len(stale) == 2
        labels = {n.label for n in stale}
        assert "Stale" in labels
        assert "Unknown" in labels


class TestDatasetStatusRecord:
    """Tests for DatasetStatusRecord dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating with minimal fields."""
        dataset_id = uuid4()
        record = DatasetStatusRecord(dataset_id=dataset_id)

        assert record.dataset_id == dataset_id
        assert record.last_pipeline_run is None
        assert record.last_pipeline_status is None
        assert record.source_delay_detected is False

    def test_create_full(self) -> None:
        """Test creating with all fields."""
        dataset_id = uuid4()
        now = datetime.now(UTC)

        record = DatasetStatusRecord(
            dataset_id=dataset_id,
            last_pipeline_run=now,
            last_pipeline_status="success",
            rows_processed=1000,
            source_delay_detected=False,
        )

        assert record.last_pipeline_run == now
        assert record.last_pipeline_status == "success"
        assert record.rows_processed == 1000


class TestLocalOrchestrator:
    """Tests for LocalOrchestrator."""

    def test_kind_is_local(self) -> None:
        """Test orchestrator kind."""
        orch = LocalOrchestrator()
        assert orch.kind == "local"

    @pytest.mark.asyncio
    async def test_submit_run(self) -> None:
        """Test submitting a run."""
        orch = LocalOrchestrator(max_workers=2)

        run_id = uuid4()
        flow_def = {"nodes": [], "edges": []}

        result = await orch.submit_run(
            run_id=run_id,
            flow_definition=flow_def,
            config={"mode": "overwrite"},
            tags={"tenant_id": str(uuid4())},
        )

        assert result.orchestrator_kind == "local"
        assert result.orchestrator_run_id is not None
        assert "nodes" in result.orchestrator_meta

        orch.cleanup()

    @pytest.mark.asyncio
    async def test_get_status_unknown(self) -> None:
        """Test getting status for unknown run."""
        orch = LocalOrchestrator()

        status = await orch.get_status("nonexistent")

        assert status.status == "unknown"
        assert "not found" in status.error_message.lower()

        orch.cleanup()

    @pytest.mark.asyncio
    async def test_submit_and_poll(self) -> None:
        """Test submitting and polling a run."""

        # Create custom executor that completes immediately
        async def mock_executor(node_id, node_type, code_ref, config):
            return {"status": "success"}

        orch = LocalOrchestrator(max_workers=2, node_executor=mock_executor)

        run_id = uuid4()
        node_id = str(uuid4())

        flow_def = {
            "nodes": [
                {
                    "id": node_id,
                    "label": "Test",
                    "type": "Dataset",
                    "resource_id": node_id,
                    "code_ref": "TestPipeline",
                    "config": {},
                    "status": "pending",
                }
            ],
            "edges": [],
        }

        result = await orch.submit_run(
            run_id=run_id,
            flow_definition=flow_def,
            config={"mode": "overwrite"},
            tags={},
        )

        # Give async execution time to complete
        await asyncio.sleep(0.2)

        status = await orch.get_status(result.orchestrator_run_id)
        assert status.status in ("running", "completed")

        orch.cleanup()

    @pytest.mark.asyncio
    async def test_cancel_run(self) -> None:
        """Test cancelling a run."""

        # Use a slow executor
        async def slow_executor(node_id, node_type, code_ref, config):
            await asyncio.sleep(10)
            return {"status": "success"}

        orch = LocalOrchestrator(max_workers=1, node_executor=slow_executor)

        run_id = uuid4()
        node_id = str(uuid4())

        flow_def = {
            "nodes": [
                {
                    "id": node_id,
                    "label": "Slow",
                    "type": "Dataset",
                    "resource_id": node_id,
                    "code_ref": "SlowPipeline",
                    "config": {},
                    "status": "pending",
                }
            ],
            "edges": [],
        }

        result = await orch.submit_run(
            run_id=run_id,
            flow_definition=flow_def,
            config={},
            tags={},
        )

        # Let it start
        await asyncio.sleep(0.1)

        # Cancel
        success = await orch.cancel_run(result.orchestrator_run_id)
        assert success is True

        status = await orch.get_status(result.orchestrator_run_id)
        assert status.status == "cancelled"

        orch.cleanup()

    @pytest.mark.asyncio
    async def test_get_logs(self) -> None:
        """Test getting logs from a run."""

        async def mock_executor(node_id, node_type, code_ref, config):
            return {"status": "success"}

        orch = LocalOrchestrator(node_executor=mock_executor)

        run_id = uuid4()
        node_id = str(uuid4())

        # Use a flow with a node so logs are generated
        flow_def = {
            "nodes": [
                {
                    "id": node_id,
                    "label": "Test",
                    "type": "Dataset",
                    "resource_id": node_id,
                    "code_ref": "TestPipeline",
                    "config": {},
                    "status": "pending",
                }
            ],
            "edges": [],
        }

        result = await orch.submit_run(
            run_id=run_id,
            flow_definition=flow_def,
            config={},
            tags={},
        )

        # Wait for completion
        await asyncio.sleep(0.2)

        # Get logs
        logs = await orch.get_logs(result.orchestrator_run_id)
        assert "started" in logs.lower()

        orch.cleanup()


class TestOrchestratorAdapterInterface:
    """Tests for OrchestratorAdapter abstract interface."""

    def test_cannot_instantiate_abstract(self) -> None:
        """Test that OrchestratorAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            OrchestratorAdapter()

    def test_local_implements_interface(self) -> None:
        """Test LocalOrchestrator implements the interface."""
        orch = LocalOrchestrator()

        assert isinstance(orch, OrchestratorAdapter)
        assert hasattr(orch, "kind")
        assert hasattr(orch, "submit_run")
        assert hasattr(orch, "get_status")
        assert hasattr(orch, "cancel_run")
        assert hasattr(orch, "get_logs")

        orch.cleanup()


class TestSubmitResult:
    """Tests for SubmitResult dataclass."""

    def test_create(self) -> None:
        """Test creating a SubmitResult."""
        result = SubmitResult(
            orchestrator_run_id="abc123",
            orchestrator_kind="local",
            orchestrator_meta={"nodes": 5},
        )

        assert result.orchestrator_run_id == "abc123"
        assert result.orchestrator_kind == "local"
        assert result.orchestrator_meta["nodes"] == 5


class TestRunStatus:
    """Tests for RunStatus dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating with minimal fields."""
        status = RunStatus(status="running")

        assert status.status == "running"
        assert status.error_message is None
        assert status.metrics is None

    def test_create_full(self) -> None:
        """Test creating with all fields."""
        now = datetime.now(UTC)

        status = RunStatus(
            status="completed",
            error_message=None,
            metrics={"rows": 1000},
            started_at=now,
            finished_at=now,
        )

        assert status.status == "completed"
        assert status.metrics == {"rows": 1000}
        assert status.started_at == now


class TestNodeData:
    """Tests for NodeData dataclass."""

    def test_create(self) -> None:
        """Test creating NodeData."""
        resource_id = uuid4()
        data = NodeData(
            resource_id=resource_id,
            name="Test Dataset",
            resource_type="DatasetInstance",
            code_ref="ExpressionPipeline",
            status="fresh",
        )

        assert data.resource_id == resource_id
        assert data.name == "Test Dataset"
        assert data.resource_type == "DatasetInstance"
        assert data.code_ref == "ExpressionPipeline"
        assert data.status == "fresh"
        assert data.config == {}


class TestGraphNode:
    """Tests for GraphNode dataclass."""

    def test_create(self) -> None:
        """Test creating GraphNode."""
        resource_id = uuid4()
        data = NodeData(
            resource_id=resource_id,
            name="Test",
            resource_type="Dataset",
        )

        node = GraphNode(
            id=str(resource_id),
            label="Test",
            type="Dataset",
            data=data,
        )

        assert node.id == str(resource_id)
        assert node.label == "Test"
        assert node.type == "Dataset"
        assert node.data == data


class TestGraphEdge:
    """Tests for GraphEdge dataclass."""

    def test_create(self) -> None:
        """Test creating GraphEdge."""
        source = str(uuid4())
        target = str(uuid4())

        edge = GraphEdge(source=source, target=target)

        assert edge.source == source
        assert edge.target == target


class TestLocalRunState:
    """Tests for LocalRunState dataclass."""

    def test_create(self) -> None:
        """Test creating LocalRunState."""
        run_id = uuid4()
        state = LocalRunState(
            run_id=run_id,
            flow_definition={"nodes": [], "edges": []},
            config={"mode": "overwrite"},
            tags={"tenant_id": "123"},
        )

        assert state.run_id == run_id
        assert state.status == "queued"
        assert state.cancelled is False
        assert state.node_results == {}
        assert state.logs == []


# ============================================================================
# Freshness and Lineage Tests
# ============================================================================


class TestUpdateFrequency:
    """Tests for UpdateFrequency dataclass."""

    def test_create_default(self) -> None:
        """Test creating with defaults."""
        freq = UpdateFrequency()

        assert freq.frequency == "daily"
        assert freq.grace_period_days == 0
        assert freq.business_days_only is False
        assert freq.day_of_week is None

    def test_daily_expected_date(self) -> None:
        """Test daily frequency expected date."""
        freq = UpdateFrequency(frequency="daily")
        as_of = date(2025, 1, 15)  # Wednesday

        expected = freq.get_expected_date(as_of)
        assert expected == date(2025, 1, 14)  # Tuesday

    def test_daily_business_days_expected_date(self) -> None:
        """Test daily business days expected date."""
        freq = UpdateFrequency(frequency="daily", business_days_only=True)

        # Monday -> expect Friday
        expected = freq.get_expected_date(date(2025, 1, 13))
        assert expected == date(2025, 1, 10)  # Friday

        # Wednesday -> expect Tuesday
        expected = freq.get_expected_date(date(2025, 1, 15))
        assert expected == date(2025, 1, 14)

    def test_weekly_expected_date(self) -> None:
        """Test weekly frequency expected date."""
        freq = UpdateFrequency(frequency="weekly", day_of_week=0)  # Monday
        as_of = date(2025, 1, 15)  # Wednesday

        expected = freq.get_expected_date(as_of)
        assert expected == date(2025, 1, 13)  # Previous Monday

    def test_monthly_expected_date(self) -> None:
        """Test monthly frequency expected date."""
        freq = UpdateFrequency(frequency="monthly")
        as_of = date(2025, 1, 15)

        expected = freq.get_expected_date(as_of)
        assert expected == date(2024, 12, 31)  # End of previous month

    def test_quarterly_expected_date(self) -> None:
        """Test quarterly frequency expected date."""
        freq = UpdateFrequency(frequency="quarterly")

        # Q1 expects Q4 of previous year
        expected = freq.get_expected_date(date(2025, 2, 15))
        assert expected == date(2024, 12, 31)

        # Q2 expects end of Q1
        expected = freq.get_expected_date(date(2025, 4, 15))
        assert expected == date(2025, 3, 31)

    def test_is_stale_with_fresh_data(self) -> None:
        """Test staleness check with fresh data."""
        freq = UpdateFrequency(frequency="daily")
        as_of = date(2025, 1, 15)
        last_data_date = date(2025, 1, 14)  # Yesterday

        assert freq.is_stale(last_data_date, as_of) is False

    def test_is_stale_with_stale_data(self) -> None:
        """Test staleness check with stale data."""
        freq = UpdateFrequency(frequency="daily")
        as_of = date(2025, 1, 15)
        last_data_date = date(2025, 1, 10)  # 5 days ago

        assert freq.is_stale(last_data_date, as_of) is True

    def test_is_stale_with_grace_period(self) -> None:
        """Test staleness check with grace period."""
        freq = UpdateFrequency(frequency="daily", grace_period_days=2)
        as_of = date(2025, 1, 15)

        # Expected date = Jan 14, threshold = Jan 14 - 2 = Jan 12
        # Data from 4 days ago (Jan 11) - should be stale (< Jan 12)
        last_data_date = date(2025, 1, 11)
        assert freq.is_stale(last_data_date, as_of) is True

        # Data exactly at threshold (Jan 12) - should NOT be stale (>= Jan 12)
        last_data_date = date(2025, 1, 12)
        assert freq.is_stale(last_data_date, as_of) is False

        # Data from 2 days ago (Jan 13) - within grace period
        last_data_date = date(2025, 1, 13)
        assert freq.is_stale(last_data_date, as_of) is False

    def test_is_stale_with_none_date(self) -> None:
        """Test staleness check with no data date."""
        freq = UpdateFrequency()
        assert freq.is_stale(None, date.today()) is True


class TestDatasetStatus:
    """Tests for DatasetStatus enum."""

    def test_enum_values(self) -> None:
        """Test all enum values exist."""
        assert DatasetStatus.NOT_INITIALIZED == "not_initialized"
        assert DatasetStatus.READY == "ready"
        assert DatasetStatus.STALE == "stale"
        assert DatasetStatus.STALE_SOURCE_DELAYED == "stale_source_delayed"
        assert DatasetStatus.ERROR == "error"


class TestFreshnessReport:
    """Tests for FreshnessReport dataclass."""

    def test_create_ready(self) -> None:
        """Test creating a ready report."""
        resource_id = uuid4()
        report = FreshnessReport(
            resource_id=resource_id,
            status=DatasetStatus.READY,
            last_data_date=date.today() - timedelta(days=1),
            expected_date=date.today() - timedelta(days=1),
            all_ready=True,
        )

        assert report.resource_id == resource_id
        assert report.status == DatasetStatus.READY
        assert report.all_ready is True
        assert report.blocking_resources == []

    def test_create_with_blockers(self) -> None:
        """Test creating report with blocking resources."""
        resource_id = uuid4()
        blocker1 = uuid4()
        blocker2 = uuid4()

        report = FreshnessReport(
            resource_id=resource_id,
            status=DatasetStatus.STALE,
            all_ready=False,
            blocking_resources=[blocker1, blocker2],
            status_map={
                blocker1: DatasetStatus.STALE,
                blocker2: DatasetStatus.ERROR,
            },
        )

        assert report.all_ready is False
        assert len(report.blocking_resources) == 2
        assert report.status_map[blocker1] == DatasetStatus.STALE


class TestLineageFreshnessReport:
    """Tests for LineageFreshnessReport dataclass."""

    def test_create(self) -> None:
        """Test creating a lineage freshness report."""
        resource_id = uuid4()
        report = LineageFreshnessReport(
            resource_id=resource_id,
            all_ready=True,
        )

        assert report.resource_id == resource_id
        assert report.all_ready is True
        assert report.blocking_resources == []
        assert report.status_map == {}


class TestUpstreamNotReadyError:
    """Tests for UpstreamNotReadyError exception."""

    def test_create(self) -> None:
        """Test creating the exception."""
        blockers = [uuid4(), uuid4()]
        error = UpstreamNotReadyError(
            message="2 upstreams not ready",
            blocking_resources=blockers,
        )

        assert str(error) == "2 upstreams not ready"
        assert error.blocking_resources == blockers

    def test_raise_and_catch(self) -> None:
        """Test raising and catching the exception."""
        blockers = [uuid4()]

        with pytest.raises(UpstreamNotReadyError) as exc_info:
            raise UpstreamNotReadyError(
                message="Upstream stale",
                blocking_resources=blockers,
            )

        assert exc_info.value.blocking_resources == blockers


class TestLineageResolver:
    """Tests for LineageResolver class."""

    def test_create(self) -> None:
        """Test creating a LineageResolver."""
        resolver = LineageResolver()
        assert resolver is not None
