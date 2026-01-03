"""Tests for RunExecutionService.

Tests the central coordination of run execution, including:
- Submission to orchestrator
- Status polling and syncing
- Guardrails integration
- Activity emission
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import ActorContext
from libs.db.models.activity import Activity
from libs.db.models.resource import Resource
from libs.db.models.quant import DatasetInstance, ExperimentInstance
from libs.orchestration.adapter import OrchestratorAdapter, RunStatus, SubmitResult
from libs.orchestration.run_service import RunExecutionService
from libs.orchestration.status_store import StatusStore
from optaic.guardrails.runtime.engine import GuardrailsEngine


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_actor():
    """Mock actor context."""
    return ActorContext(
        id=uuid4(),
        tenant_id=uuid4(),
    )


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator adapter."""
    orch = MagicMock(spec=OrchestratorAdapter)
    orch.submit_run = AsyncMock()
    orch.get_status = AsyncMock()
    orch.cancel_run = AsyncMock()
    orch.get_logs = AsyncMock()
    return orch


@pytest.fixture
def mock_status_store():
    """Mock status store."""
    store = MagicMock(spec=StatusStore)
    store.mark_run_start = AsyncMock()
    store.mark_run_success = AsyncMock()
    store.mark_run_error = AsyncMock()
    store.get_status = AsyncMock()
    return store


@pytest.fixture
def mock_guardrails():
    """Mock guardrails engine."""
    engine = MagicMock(spec=GuardrailsEngine)
    engine.validate_at_gate = AsyncMock()
    return engine


@pytest.fixture
def run_service(mock_orchestrator, mock_status_store, mock_guardrails):
    """Create RunExecutionService with mocks."""
    return RunExecutionService(
        orchestrator=mock_orchestrator,
        status_store=mock_status_store,
        guardrails_engine=mock_guardrails,
    )


@pytest.mark.asyncio
class TestRunExecutionService:
    """Tests for RunExecutionService."""

    async def test_submit_pipeline_run_success(
        self,
        run_service,
        mock_session,
        mock_actor,
        mock_orchestrator,
        mock_status_store,
        mock_guardrails,
    ):
        """Test successful pipeline run submission."""
        # Setup
        dataset_id = uuid4()

        # Mock resources
        dataset = DatasetInstance(
            resource_id=dataset_id,
            tenant_id=mock_actor.tenant_id,
            pipeline_instance_id=uuid4(),
            store_instance_id=uuid4(),
            accessor_instance_id=uuid4(),
        )
        resource = Resource(id=dataset_id, name="Test Dataset")

        mock_session.get.side_effect = lambda model, id: {
            DatasetInstance: dataset,
            Resource: resource if id == dataset_id else None,
        }.get(model)

        # Mock build_graph
        with patch(
            "libs.orchestration.run_service.build_graph", new_callable=AsyncMock
        ) as mock_build_graph:
            mock_graph = MagicMock()
            mock_graph.nodes = {"node1": {}}
            mock_graph.to_dict.return_value = {"nodes": [], "edges": []}
            mock_build_graph.return_value = mock_graph

            # Mock orchestrator result
            mock_orchestrator.submit_run.return_value = SubmitResult(
                orchestrator_run_id="orch-123",
                orchestrator_kind="test",
                orchestrator_meta={},
            )

            # Test
            result = await run_service.submit_pipeline_run(
                session=mock_session,
                actor=mock_actor,
                dataset_id=dataset_id,
                mode="incremental",
            )

            # Assertions
            assert result["status"] == "running"
            assert result["orchestrator_run_id"] == "orch-123"

            # Check guardrails called
            mock_guardrails.validate_at_gate.assert_called_once()
            call_kwargs = mock_guardrails.validate_at_gate.call_args.kwargs
            assert call_kwargs["scope"] == "run"
            assert call_kwargs["resource_id"] == str(dataset_id)
            assert call_kwargs["target_snapshot"]["mode"] == "incremental"

            # Check DB activity
            assert mock_session.add.call_count >= 2  # Run resource + Activity + Outbox

            # Verify Run resource created (inspect mock calls or args)
            # Find the call that adds a Resource
            added_resources = [call[0][0] for call in mock_session.add.call_args_list]
            run_resource = next(
                r
                for r in added_resources
                if isinstance(r, Resource) and r.type == "PipelineRun"
            )
            assert run_resource.parent_id == dataset_id
            assert run_resource.metadata_json["orchestrator_run_id"] == "orch-123"

            # Verify status store update
            mock_status_store.mark_run_start.assert_called_once_with(dataset_id)

    async def test_submit_pipeline_run_fresh_check(
        self,
        run_service,
        mock_session,
        mock_actor,
        mock_status_store,
    ):
        """Test submission logic when dataset is already fresh."""
        dataset_id = uuid4()

        # Mock status showing success
        mock_status_store.get_status.return_value = MagicMock(
            last_pipeline_status="success"
        )

        # Mock dataset as fresh
        mock_session.get.return_value = DatasetInstance(
            resource_id=dataset_id, freshness_status="fresh"
        )

        # Should fail without force=True
        with pytest.raises(ValueError, match="already fresh"):
            await run_service.submit_pipeline_run(
                session=mock_session,
                actor=mock_actor,
                dataset_id=dataset_id,
                force=False,
            )

        # Should succeed with force=True (mocking setup for success path would be needed strictly,
        # but here we just check we get past the fresh check logic)
        mock_session.get.side_effect = lambda model, id: (
            DatasetInstance(resource_id=dataset_id, freshness_status="fresh")
            if model == DatasetInstance
            else Resource(id=dataset_id, name="Test")
        )

        with patch(
            "libs.orchestration.run_service.build_graph", new_callable=AsyncMock
        ) as mock_build:
            mock_build.return_value = MagicMock(nodes={}, to_dict=lambda: {})
            run_service._orchestrator.submit_run.return_value = SubmitResult(
                "id", "kind", {}
            )

            await run_service.submit_pipeline_run(
                session=mock_session,
                actor=mock_actor,
                dataset_id=dataset_id,
                force=True,
            )

    async def test_submit_experiment_run(
        self,
        run_service,
        mock_session,
        mock_actor,
        mock_orchestrator,
        mock_guardrails,
    ):
        """Test successful experiment run submission."""
        experiment_id = uuid4()

        mock_session.get.side_effect = lambda model, id: (
            ExperimentInstance(
                resource_id=experiment_id,
                expression_text="MEAN(X)",
                input_datasets_json={},
            )
            if model == ExperimentInstance
            else Resource(id=experiment_id, name="Exp")
        )

        mock_orchestrator.submit_run.return_value = SubmitResult(
            orchestrator_run_id="exp-run-1",
            orchestrator_kind="local",
            orchestrator_meta={},
        )

        result = await run_service.submit_experiment_run(
            session=mock_session,
            actor=mock_actor,
            experiment_id=experiment_id,
            limit=50,
        )

        assert result["status"] == "running"
        assert result["orchestrator_run_id"] == "exp-run-1"

        # Check guardrails
        mock_guardrails.validate_at_gate.assert_called_once()
        assert (
            mock_guardrails.validate_at_gate.call_args.kwargs["target_snapshot"][
                "limit"
            ]
            == 50
        )

    async def test_poll_and_sync_running(
        self,
        run_service,
        mock_session,
        mock_orchestrator,
    ):
        """Test polling a running task."""
        run_id = uuid4()
        run = Resource(
            id=run_id,
            type="PipelineRun",
            metadata_json={"orchestrator_run_id": "orch-1", "status": "running"},
        )
        mock_session.get.return_value = run

        mock_orchestrator.get_status.return_value = RunStatus(
            status="running",
            metrics={"rows": 50},
        )

        result = await run_service.poll_and_sync(mock_session, run_id)

        assert result["status"] == "running"
        assert run.metadata_json["status"] == "running"  # No change

        # Verify no completion hooks called
        assert mock_session.add.call_count == 0  # No activity emitted

    async def test_poll_and_sync_completed(
        self,
        run_service,
        mock_session,
        mock_orchestrator,
        mock_status_store,
    ):
        """Test polling a task that just completed."""
        run_id = uuid4()
        parent_id = uuid4()

        run = Resource(
            id=run_id,
            type="PipelineRun",
            parent_id=parent_id,
            metadata_json={"orchestrator_run_id": "orch-1", "status": "running"},
        )

        dataset = DatasetInstance(resource_id=parent_id)

        # Mock gets for run AND parent dataset
        mock_session.get.side_effect = lambda model, id: (
            run if id == run_id else dataset if id == parent_id else None
        )

        mock_orchestrator.get_status.return_value = RunStatus(
            status="completed",
            metrics={"rows_processed": 100, "last_data_date": "2025-01-01"},
        )

        result = await run_service.poll_and_sync(mock_session, run_id)

        assert result["status"] == "completed"
        assert run.metadata_json["status"] == "completed"

        # Check dataset update
        assert dataset.freshness_status == "fresh"

        # Check status store update
        mock_status_store.mark_run_success.assert_called_once()
        assert (
            mock_status_store.mark_run_success.call_args.kwargs["rows_processed"] == 100
        )

        # Check activity emitted
        added_objs = [call[0][0] for call in mock_session.add.call_args_list]
        activity = next(a for a in added_objs if isinstance(a, Activity))
        assert activity.action == "pipelinerun.run_completed"

    async def test_cancel_run(
        self,
        run_service,
        mock_session,
        mock_actor,
        mock_orchestrator,
    ):
        """Test cancelling a run."""
        run_id = uuid4()
        run = Resource(
            id=run_id,
            type="PipelineRun",
            metadata_json={"orchestrator_run_id": "orch-1", "status": "running"},
        )
        mock_session.get.return_value = run
        mock_orchestrator.cancel_run.return_value = True

        result = await run_service.cancel_run(mock_session, mock_actor, run_id)

        assert result["status"] == "cancelled"
        assert run.metadata_json["status"] == "cancelled"

        mock_orchestrator.cancel_run.assert_called_once_with("orch-1")
