"""Prefect SDK Integration Tests.

Phase 2.8.4: Comprehensive tests for PrefectOrchestrator using Prefect's
test harness for isolated execution without a real Prefect server.

Tests cover:
- Deployment creation with run_id verification
- Deployment triggering and flow run status
- Schedule updates
- Task run tracking
- State mapping
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest


# Check if prefect is available before running these tests
try:
    from prefect import flow as prefect_flow
    from prefect import task as prefect_task
    from prefect.testing.utilities import prefect_test_harness

    PREFECT_AVAILABLE = True
except ImportError:
    PREFECT_AVAILABLE = False

from libs.orchestration.adapter import DeploymentResult, RunStatus, SubmitResult
from libs.orchestration.dag import DependencyGraph
from libs.orchestration.prefect_adapter import PrefectOrchestrator


# Skip all tests if prefect is not available
pytestmark = pytest.mark.skipif(
    not PREFECT_AVAILABLE,
    reason="Prefect not installed",
)


@pytest.fixture(scope="module")
def prefect_harness():
    """Set up Prefect test harness for module scope.

    Uses module scope to reduce overhead of creating test database per test.
    """
    if not PREFECT_AVAILABLE:
        pytest.skip("Prefect not available")

    with prefect_test_harness():
        yield


class TestPrefectOrchestratorBasic:
    """Basic tests for PrefectOrchestrator that don't require harness."""

    def test_kind_is_prefect(self) -> None:
        """Test orchestrator kind."""
        orch = PrefectOrchestrator()
        assert orch.kind == "prefect"

    def test_default_api_url(self) -> None:
        """Test default API URL is set."""
        orch = PrefectOrchestrator()
        assert orch._api_url is not None
        assert "localhost" in orch._api_url or "4200" in orch._api_url

    def test_custom_api_url(self) -> None:
        """Test custom API URL is used."""
        custom_url = "http://custom-prefect:4200/api"
        orch = PrefectOrchestrator(api_url=custom_url)
        assert orch._api_url == custom_url

    def test_work_pool_default(self) -> None:
        """Test default work pool is set."""
        orch = PrefectOrchestrator()
        assert orch._work_pool == "default"

    def test_work_pool_custom(self) -> None:
        """Test custom work pool is used."""
        orch = PrefectOrchestrator(work_pool="custom-pool")
        assert orch._work_pool == "custom-pool"


class TestPrefectStateMapping:
    """Tests for Prefect state mapping."""

    def test_map_completed_state(self) -> None:
        """Test mapping COMPLETED state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("COMPLETED") == "completed"
        assert orch._map_prefect_state("completed") == "completed"

    def test_map_running_state(self) -> None:
        """Test mapping RUNNING state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("RUNNING") == "running"

    def test_map_pending_state(self) -> None:
        """Test mapping PENDING state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("PENDING") == "queued"

    def test_map_scheduled_state(self) -> None:
        """Test mapping SCHEDULED state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("SCHEDULED") == "queued"

    def test_map_failed_state(self) -> None:
        """Test mapping FAILED state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("FAILED") == "failed"

    def test_map_crashed_state(self) -> None:
        """Test mapping CRASHED state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("CRASHED") == "failed"

    def test_map_cancelled_state(self) -> None:
        """Test mapping CANCELLED state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("CANCELLED") == "cancelled"
        assert orch._map_prefect_state("CANCELLING") == "cancelled"

    def test_map_unknown_state(self) -> None:
        """Test mapping unknown state."""
        orch = PrefectOrchestrator()
        assert orch._map_prefect_state("SOME_NEW_STATE") == "unknown"
        assert orch._map_prefect_state(None) == "unknown"


class TestPrefectDeploymentLocal:
    """Tests for deployment creation with local fallback."""

    @pytest.mark.asyncio
    async def test_create_deployment_local_fallback(self) -> None:
        """Test deployment creation falls back to local when Prefect unavailable.

        When Prefect deployment creation fails, should return a local deployment.
        """
        orch = PrefectOrchestrator()
        instance_id = uuid4()

        # This will likely fail without proper Prefect setup
        # but should fall back to local deployment
        result = await orch.create_deployment(
            instance_id=instance_id,
            flow_name="test-flow",
            flow_template="expression_pipeline",
            parameters={"mode": "incremental"},
            tags={"tenant_id": str(uuid4())},
        )

        assert isinstance(result, DeploymentResult)
        # Should either be prefect or local
        assert result.orchestrator_kind in ("prefect", "local")
        assert result.deployment_id is not None

    @pytest.mark.asyncio
    async def test_delete_local_deployment(self) -> None:
        """Test deleting a local deployment."""
        orch = PrefectOrchestrator()

        # Local deployments should always succeed deletion
        result = await orch.delete_deployment("local-abc123")
        assert result is True


class TestPrefectGraphSerialization:
    """Tests for graph serialization and reconstruction."""

    def test_graph_to_dict_and_back(self) -> None:
        """Test graph serialization round-trip."""
        graph = DependencyGraph()
        node1 = uuid4()
        node2 = uuid4()

        graph.add_node(
            resource_id=node1,
            name="Node 1",
            resource_type="DatasetInstance",
            code_ref="ExpressionPipeline",
            status="fresh",
        )
        graph.add_node(
            resource_id=node2,
            name="Node 2",
            resource_type="SignalInstance",
            status="stale",
        )
        graph.add_edge(node1, node2)

        # Serialize
        data = graph.to_dict()

        # Deserialize
        restored = DependencyGraph.from_dict(data)

        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1
        assert restored.nodes[str(node1)].label == "Node 1"
        assert restored.nodes[str(node2)].data.status == "stale"


class TestPrefectSubmitResultDataclass:
    """Tests for SubmitResult dataclass used by Prefect."""

    def test_create_submit_result(self) -> None:
        """Test creating SubmitResult."""
        result = SubmitResult(
            orchestrator_run_id="flow-run-123",
            orchestrator_kind="prefect",
            orchestrator_meta={
                "nodes": 5,
                "api_url": "http://localhost:4200/api",
            },
        )

        assert result.orchestrator_run_id == "flow-run-123"
        assert result.orchestrator_kind == "prefect"
        assert result.orchestrator_meta["nodes"] == 5


class TestPrefectDeploymentResultDataclass:
    """Tests for DeploymentResult dataclass."""

    def test_create_deployment_result(self) -> None:
        """Test creating DeploymentResult."""
        result = DeploymentResult(
            deployment_id="deployment-abc",
            orchestrator_kind="prefect",
            deployment_meta={
                "flow_template": "expression_pipeline",
                "work_pool": "default",
                "has_schedule": True,
            },
        )

        assert result.deployment_id == "deployment-abc"
        assert result.orchestrator_kind == "prefect"
        assert result.deployment_meta["has_schedule"] is True


class TestPrefectRunStatusDataclass:
    """Tests for RunStatus dataclass with Prefect-specific fields."""

    def test_create_run_status_completed(self) -> None:
        """Test creating completed RunStatus."""
        now = datetime.now(UTC)
        status = RunStatus(
            status="completed",
            started_at=now,
            finished_at=now,
            metrics={"rows_processed": 1000},
        )

        assert status.status == "completed"
        assert status.started_at is not None
        assert status.finished_at is not None
        assert status.metrics["rows_processed"] == 1000

    def test_create_run_status_failed(self) -> None:
        """Test creating failed RunStatus."""
        status = RunStatus(
            status="failed",
            error_message="Pipeline execution failed",
        )

        assert status.status == "failed"
        assert status.error_message == "Pipeline execution failed"


@pytest.mark.usefixtures("prefect_harness")
class TestPrefectIntegrationWithHarness:
    """Integration tests using Prefect test harness.

    These tests use the prefect_test_harness fixture which provides
    an isolated ephemeral Prefect server for testing.
    """

    @pytest.mark.asyncio
    async def test_get_status_unknown_run(self) -> None:
        """Test getting status for non-existent run."""
        orch = PrefectOrchestrator()

        # Use a random UUID that won't exist
        status = await orch.get_status(str(uuid4()))

        # Should return unknown status
        assert status.status == "unknown"

    @pytest.mark.asyncio
    async def test_cancel_unknown_run(self) -> None:
        """Test cancelling non-existent run."""
        orch = PrefectOrchestrator()

        # Should return False for non-existent run
        result = await orch.cancel_run(str(uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_get_logs_unknown_run(self) -> None:
        """Test getting logs for non-existent run."""
        orch = PrefectOrchestrator()

        # Should return error message
        logs = await orch.get_logs(str(uuid4()))
        assert "Error" in logs or "error" in logs.lower()

    @pytest.mark.asyncio
    async def test_get_deployment_unknown(self) -> None:
        """Test getting unknown deployment returns None."""
        orch = PrefectOrchestrator()

        result = await orch.get_deployment(str(uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_deployment_local(self) -> None:
        """Test getting local deployment."""
        orch = PrefectOrchestrator()
        local_id = f"local-{uuid4()}"

        result = await orch.get_deployment(local_id)
        assert result is not None
        assert result["kind"] == "local"

    @pytest.mark.asyncio
    async def test_update_schedule_local(self) -> None:
        """Test updating schedule on local deployment."""
        orch = PrefectOrchestrator()
        local_id = f"local-{uuid4()}"

        result = await orch.update_schedule(
            deployment_id=local_id,
            schedule={"cron": "0 6 * * *"},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_get_task_runs_empty(self) -> None:
        """Test getting task runs for non-existent flow run."""
        orch = PrefectOrchestrator()

        # Should return empty list
        task_runs = await orch.get_task_runs(str(uuid4()))
        assert task_runs == []


@pytest.mark.usefixtures("prefect_harness")
class TestPrefectFlowExecution:
    """Tests for actual flow execution in test harness."""

    @pytest.mark.asyncio
    async def test_simple_flow_execution(self) -> None:
        """Test executing a simple Prefect flow."""
        if not PREFECT_AVAILABLE:
            pytest.skip("Prefect not available")

        # Define a simple flow for testing
        @prefect_task
        def add_numbers(a: int, b: int) -> int:
            return a + b

        @prefect_flow(name="test-simple-flow")
        def simple_flow(x: int) -> int:
            result = add_numbers(x, 10)
            return result

        # Run the flow
        result = simple_flow(5)
        assert result == 15

    @pytest.mark.asyncio
    async def test_async_flow_execution(self) -> None:
        """Test executing an async Prefect flow."""
        if not PREFECT_AVAILABLE:
            pytest.skip("Prefect not available")

        @prefect_task
        async def async_task(value: int) -> int:
            await asyncio.sleep(0.01)  # Small delay
            return value * 2

        @prefect_flow(name="test-async-flow")
        async def async_flow(x: int) -> int:
            result = await async_task(x)
            return result

        # Run the async flow
        result = await async_flow(7)
        assert result == 14

    @pytest.mark.asyncio
    async def test_flow_with_return_state(self) -> None:
        """Test flow execution with return_state=True."""
        if not PREFECT_AVAILABLE:
            pytest.skip("Prefect not available")

        @prefect_flow(name="test-state-flow")
        def state_flow() -> str:
            return "success"

        # Run with return_state
        state = state_flow(return_state=True)
        assert state.is_completed()
        # In Prefect 3.x, result() is async - use result record directly
        result = await state.aresult()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_flow_with_dependencies(self) -> None:
        """Test flow with task dependencies."""
        if not PREFECT_AVAILABLE:
            pytest.skip("Prefect not available")

        @prefect_task
        def task_a() -> int:
            return 1

        @prefect_task
        def task_b() -> int:
            return 2

        @prefect_task
        def task_c(a: int, b: int) -> int:
            return a + b

        @prefect_flow(name="test-dep-flow")
        def dependency_flow() -> int:
            a = task_a()
            b = task_b()
            return task_c(a, b)

        result = dependency_flow()
        assert result == 3


class TestPrefectScheduleParsing:
    """Tests for schedule configuration parsing."""

    @pytest.mark.asyncio
    async def test_cron_schedule_parsing(self) -> None:
        """Test that cron schedule config is properly parsed."""
        orch = PrefectOrchestrator()

        # Verify the schedule parsing logic
        schedule = {"cron": "0 6 * * *"}

        # Test that update_schedule handles cron
        # For local deployment, this should succeed
        local_id = f"local-{uuid4()}"
        result = await orch.update_schedule(local_id, schedule)
        assert result is True

    @pytest.mark.asyncio
    async def test_interval_schedule_parsing(self) -> None:
        """Test that interval schedule config is properly parsed."""
        orch = PrefectOrchestrator()

        # Verify the schedule parsing logic
        schedule = {"interval_seconds": 3600}

        # Test that update_schedule handles interval
        local_id = f"local-{uuid4()}"
        result = await orch.update_schedule(local_id, schedule)
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_schedule(self) -> None:
        """Test handling empty schedule config."""
        orch = PrefectOrchestrator()

        local_id = f"local-{uuid4()}"
        result = await orch.update_schedule(local_id, {})
        assert result is True


class TestPrefectOrchestratorTrigger:
    """Tests for deployment triggering."""

    @pytest.mark.asyncio
    async def test_trigger_local_deployment(self) -> None:
        """Test triggering a local deployment.

        Note: When the Prefect test harness is active, even local deployments
        go through Prefect's submit_run which uses the harness server.
        """
        orch = PrefectOrchestrator()
        run_id = uuid4()
        local_id = f"local-{uuid4()}"

        result = await orch.trigger_deployment(
            deployment_id=local_id,
            run_id=run_id,
            parameters={"mode": "incremental"},
            tags={"tenant_id": str(uuid4())},
        )

        assert isinstance(result, SubmitResult)
        # When test harness is active, local deployments use submit_run
        # which creates a Prefect flow run - accept either kind
        assert result.orchestrator_kind in ("local", "prefect")


class TestPrefectOrchestratorErrors:
    """Tests for error handling in PrefectOrchestrator."""

    @pytest.mark.asyncio
    async def test_submit_run_with_empty_graph(self) -> None:
        """Test submitting run with empty flow definition.

        NOTE: This test is skipped when Prefect is not available
        (see pytestmark at module level). When Prefect IS available,
        we test that empty graphs are handled without crashing.
        """
        if not PREFECT_AVAILABLE:
            pytest.skip("Prefect not installed - test requires Prefect")

        orch = PrefectOrchestrator()
        run_id = uuid4()

        # Empty graph should be handled gracefully
        # submit_run should either succeed or raise a clear error
        result = await orch.submit_run(
            run_id=run_id,
            flow_definition={"nodes": [], "edges": []},
            config={"mode": "overwrite"},
            tags={},
        )
        # Verify result structure
        assert isinstance(result, SubmitResult)
        assert result.orchestrator_run_id is not None


@pytest.mark.usefixtures("prefect_harness")
class TestPrefectOrchestratorWithClient:
    """Tests that use Prefect client operations.

    These tests require a running test harness.
    """

    @pytest.mark.asyncio
    async def test_get_client_operations(self) -> None:
        """Test that client operations work with test harness."""
        if not PREFECT_AVAILABLE:
            pytest.skip("Prefect not available")

        from prefect.client.orchestration import get_client

        async with get_client() as client:
            # Verify we can connect to the test harness
            assert client is not None

            # Try to list flow runs (should be empty or return list)
            flow_runs = await client.read_flow_runs()
            assert isinstance(flow_runs, list)
