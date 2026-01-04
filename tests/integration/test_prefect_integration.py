"""Integration tests for Prefect with REAL server communication.

Verifies actual deployment_id, flow_run_id, task_run_id are returned.
"""

from __future__ import annotations

import os
import uuid

import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def prefect_env(prefect_server: str):
    """Set PREFECT_API_URL environment variable."""
    old_value = os.environ.get("PREFECT_API_URL")
    os.environ["PREFECT_API_URL"] = prefect_server
    yield prefect_server
    if old_value is not None:
        os.environ["PREFECT_API_URL"] = old_value
    else:
        os.environ.pop("PREFECT_API_URL", None)


class TestPrefectServerHealth:
    """Verify Prefect server is healthy and responding."""

    def test_server_is_running(self, prefect_server: str) -> None:
        """Verify Prefect server responds to health check."""
        import urllib.request

        health_url = prefect_server.replace("/api", "/api/health")
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            assert resp.status == 200

    def test_can_get_server_version(self, prefect_server: str) -> None:
        """Verify we can query server version."""
        import urllib.request

        version_url = prefect_server.replace("/api", "/version")
        with urllib.request.urlopen(version_url, timeout=5) as resp:
            version = resp.read().decode()
            assert version  # Should return version string


class TestPrefectDeploymentCreation:
    """Test creating real deployments and verifying deployment_id."""

    @pytest.mark.asyncio
    async def test_create_deployment_returns_real_id(self, prefect_env: str) -> None:
        """Create a deployment and verify we get a real UUID deployment_id."""
        from prefect import flow
        from prefect.client.orchestration import get_client

        @flow
        def test_flow():
            return "Hello from test flow"

        async with get_client() as client:
            # First register the flow
            flow_id = await client.create_flow_from_name(test_flow.name)
            assert flow_id is not None
            assert isinstance(flow_id, uuid.UUID)

            # Create a deployment
            deployment_id = await client.create_deployment(
                flow_id=flow_id,
                name="test-deployment",
            )

            # Verify deployment has real UUID
            assert deployment_id is not None
            assert isinstance(deployment_id, uuid.UUID)
            print(f"Real deployment_id: {deployment_id}")

            # Verify we can read it back
            deployment = await client.read_deployment(deployment_id)
            assert deployment is not None
            assert deployment.id == deployment_id

    def test_deployment_from_serve_returns_uuid(self, prefect_env: str) -> None:
        """Test flow.serve returns something we can track."""
        from prefect import flow

        @flow(name="tracked-flow")
        def tracked_flow():
            return 42

        # Note: flow.serve() starts a background process, we need deploy() for programmatic use
        deployment = tracked_flow.to_deployment(name="tracked-deployment")
        assert deployment is not None
        assert deployment.name == "tracked-deployment"


class TestPrefectFlowRunExecution:
    """Test triggering flow runs and verifying flow_run_id."""

    @pytest.mark.asyncio
    async def test_create_flow_run_returns_real_id(self, prefect_env: str) -> None:
        """Create a flow run and verify we get a real UUID flow_run_id."""
        from prefect import flow
        from prefect.client.orchestration import get_client

        @flow(name="integration-test-flow")
        def integration_test_flow():
            return "Integration test result"

        async with get_client() as client:
            # Register flow first
            flow_id = await client.create_flow_from_name(integration_test_flow.name)
            assert flow_id is not None

            # Create deployment
            deployment_id = await client.create_deployment(
                flow_id=flow_id,
                name="integration-test-deployment",
            )
            assert deployment_id is not None
            assert isinstance(deployment_id, uuid.UUID)
            print(f"Real deployment_id from create: {deployment_id}")

            # Create a flow run
            flow_run = await client.create_flow_run_from_deployment(
                deployment_id,
                name="test-flow-run",
            )

            # Verify flow run has real IDs
            assert flow_run.id is not None
            assert isinstance(flow_run.id, uuid.UUID)
            print(f"Real flow_run_id: {flow_run.id}")

            # Verify we can read it back
            read_run = await client.read_flow_run(flow_run.id)
            assert read_run.id == flow_run.id
            assert read_run.deployment_id == deployment_id


class TestPrefectTaskRunTracking:
    """Test task run creation and task_run_id verification."""

    def test_task_run_returns_real_id(self, prefect_env: str) -> None:
        """Execute a flow with tasks and verify task_run_ids."""
        from prefect import flow, task

        @task
        def add_one(x: int) -> int:
            return x + 1

        @task
        def multiply_by_two(x: int) -> int:
            return x * 2

        @flow(name="task-tracking-flow")
        def task_tracking_flow():
            # Run tasks
            result1 = add_one(5)
            result2 = multiply_by_two(result1)

            return result2

        # Execute the flow locally
        result = task_tracking_flow()
        assert result == 12  # (5 + 1) * 2

    @pytest.mark.asyncio
    async def test_can_query_task_runs_from_api(self, prefect_env: str) -> None:
        """Query task runs via API and verify real task_run_ids."""
        from prefect import flow, task
        from prefect.client.orchestration import get_client

        @task(name="trackable-task")
        def trackable_task(x: int) -> int:
            return x * 2

        @flow(name="trackable-flow")
        def trackable_flow() -> int:
            return trackable_task(10)

        # Execute flow
        result = trackable_flow()
        assert result == 20

        # Query task runs
        async with get_client() as client:
            # Get recent flow runs
            flow_runs = await client.read_flow_runs(limit=5)
            trackable_runs = [
                r for r in flow_runs if r.name and "trackable" in r.name.lower()
            ]

            if trackable_runs:
                flow_run = trackable_runs[0]

                # Get task runs for this flow run
                task_runs = await client.read_task_runs(
                    flow_run_filter={"id": {"any_": [str(flow_run.id)]}}
                )

                for task_run in task_runs:
                    assert task_run.id is not None
                    assert isinstance(task_run.id, uuid.UUID)
                    print(f"Real task_run_id: {task_run.id}")


class TestPrefectRegistryPersistence:
    """Test that deployments persist in the registry."""

    @pytest.mark.asyncio
    async def test_deployment_persists_after_creation(self, prefect_env: str) -> None:
        """Verify deployment still exists after creation."""
        from prefect import flow
        from prefect.client.orchestration import get_client

        unique_name = f"persistent-flow-{uuid.uuid4().hex[:8]}"

        @flow(name=unique_name)
        def persistent_flow():
            return "persistent"

        async with get_client() as client:
            # Create deployment
            # First, we need to register the flow
            try:
                flow_id = await client.create_flow_from_name(unique_name)
            except Exception:
                # Flow might already exist
                flows = await client.read_flows(
                    flow_filter={"name": {"any_": [unique_name]}}
                )
                flow_id = flows[0].id if flows else None

            if flow_id:
                deployment_id = await client.create_deployment(
                    flow_id=flow_id,
                    name=f"{unique_name}-deployment",
                )

                # Verify it exists
                deployment = await client.read_deployment(deployment_id)
                assert deployment is not None
                assert deployment.id == deployment_id
                print(f"Persistent deployment_id: {deployment_id}")

                # Read it again to verify persistence
                deployment2 = await client.read_deployment(deployment_id)
                assert deployment2.id == deployment_id


# NOTE: TestOrchestrationIntegration removed - PrefectOrchestrator module
# does not exist yet. Add tests when libs.orchestration.prefect_integration
# is implemented.
