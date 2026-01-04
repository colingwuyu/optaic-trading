"""Integration tests for MLflow with REAL server communication.

Verifies actual experiment_id, run_id, and artifact tracking.
"""

from __future__ import annotations

import os
import uuid

import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def mlflow_env(mlflow_server: str):
    """Set MLFLOW_TRACKING_URI environment variable."""
    old_value = os.environ.get("MLFLOW_TRACKING_URI")
    os.environ["MLFLOW_TRACKING_URI"] = mlflow_server
    yield mlflow_server
    if old_value is not None:
        os.environ["MLFLOW_TRACKING_URI"] = old_value
    else:
        os.environ.pop("MLFLOW_TRACKING_URI", None)


class TestMLflowServerHealth:
    """Verify MLflow server is healthy and responding."""

    def test_server_is_running(self, mlflow_server: str) -> None:
        """Verify MLflow server responds to health check."""
        import urllib.request

        with urllib.request.urlopen(mlflow_server, timeout=5) as resp:
            assert resp.status == 200

    def test_can_access_api(self, mlflow_server: str) -> None:
        """Verify we can create and list experiments via API."""
        import mlflow

        # Use the MLflow client to verify API access
        # This is more reliable than raw HTTP calls
        mlflow.set_tracking_uri(mlflow_server)
        client = mlflow.tracking.MlflowClient()

        # Create a test experiment
        experiment_name = f"api-test-{uuid.uuid4().hex[:8]}"
        experiment_id = client.create_experiment(experiment_name)

        # Verify we can list experiments
        experiments = client.search_experiments()
        assert len(experiments) > 0

        # Verify our experiment exists
        experiment = client.get_experiment(experiment_id)
        assert experiment.name == experiment_name


class TestMLflowExperimentCreation:
    """Test creating real experiments and verifying experiment_id."""

    def test_create_experiment_returns_real_id(self, mlflow_env: str) -> None:
        """Create an experiment and verify we get a real experiment_id."""
        import mlflow

        experiment_name = f"test-experiment-{uuid.uuid4().hex[:8]}"

        # Create experiment
        experiment_id = mlflow.create_experiment(experiment_name)

        # Verify it's a real ID
        assert experiment_id is not None
        print(f"Real experiment_id: {experiment_id}")

        # Verify it exists by fetching it
        experiment = mlflow.get_experiment(experiment_id)
        assert experiment is not None
        assert experiment.name == experiment_name
        assert experiment.experiment_id == experiment_id

    def test_get_or_create_experiment(self, mlflow_env: str) -> None:
        """Test get_or_create experiment pattern."""
        import mlflow

        experiment_name = f"get-or-create-{uuid.uuid4().hex[:8]}"

        # First call creates
        experiment = mlflow.set_experiment(experiment_name)
        first_id = experiment.experiment_id

        # Second call returns same
        experiment2 = mlflow.set_experiment(experiment_name)
        assert experiment2.experiment_id == first_id


class TestMLflowRunCreation:
    """Test creating runs and verifying run_id."""

    def test_start_run_returns_real_id(self, mlflow_env: str) -> None:
        """Start a run and verify we get a real run_id."""
        import mlflow

        experiment_name = f"run-test-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            run_id = run.info.run_id
            assert run_id is not None
            print(f"Real run_id: {run_id}")

            # Verify we can get the run
            fetched_run = mlflow.get_run(run_id)
            assert fetched_run.info.run_id == run_id

    def test_run_with_custom_name(self, mlflow_env: str) -> None:
        """Create a run with custom name."""
        import mlflow

        experiment_name = f"named-run-{uuid.uuid4().hex[:8]}"
        run_name = f"custom-run-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run(run_name=run_name) as run:
            assert run.info.run_name == run_name
            print(f"Run with name '{run_name}': {run.info.run_id}")


class TestMLflowMetricsAndParams:
    """Test logging metrics and parameters."""

    def test_log_metrics(self, mlflow_env: str) -> None:
        """Log metrics and verify they're persisted."""
        import mlflow

        experiment_name = f"metrics-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            mlflow.log_metric("accuracy", 0.95)
            mlflow.log_metric("loss", 0.05)
            mlflow.log_metric("epochs", 100)

        # Verify metrics persisted
        fetched_run = mlflow.get_run(run.info.run_id)
        metrics = fetched_run.data.metrics
        assert metrics["accuracy"] == 0.95
        assert metrics["loss"] == 0.05
        assert metrics["epochs"] == 100.0

    def test_log_params(self, mlflow_env: str) -> None:
        """Log parameters and verify they're persisted."""
        import mlflow

        experiment_name = f"params-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            mlflow.log_param("learning_rate", "0.001")
            mlflow.log_param("batch_size", "32")
            mlflow.log_param("model_type", "transformer")

        # Verify params persisted
        fetched_run = mlflow.get_run(run.info.run_id)
        params = fetched_run.data.params
        assert params["learning_rate"] == "0.001"
        assert params["batch_size"] == "32"
        assert params["model_type"] == "transformer"

    def test_log_batch_metrics(self, mlflow_env: str) -> None:
        """Log multiple steps of a metric."""
        import mlflow

        experiment_name = f"batch-metrics-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            for step in range(10):
                mlflow.log_metric("training_loss", 1.0 - (step * 0.1), step=step)

        # Verify we can read metric history
        client = mlflow.tracking.MlflowClient()
        history = client.get_metric_history(run.info.run_id, "training_loss")
        assert len(history) == 10
        assert history[0].value == 1.0
        assert history[9].value == pytest.approx(0.1, abs=0.01)


class TestMLflowArtifacts:
    """Test artifact logging.

    Note: These tests are skipped because artifact serving configuration
    varies by MLflow deployment. The core experiment/run/metrics tests
    verify the essential functionality.
    """

    def test_log_text_artifact(self, mlflow_env: str, tmp_path) -> None:
        """Log a text file as artifact."""
        import mlflow

        experiment_name = f"artifacts-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        # Create a temp file
        artifact_file = tmp_path / "config.json"
        artifact_file.write_text('{"key": "value"}')

        with mlflow.start_run() as run:
            mlflow.log_artifact(str(artifact_file))

        # Verify artifact exists
        client = mlflow.tracking.MlflowClient()
        artifacts = client.list_artifacts(run.info.run_id)
        artifact_names = [a.path for a in artifacts]
        assert "config.json" in artifact_names

    def test_log_dict_as_artifact(self, mlflow_env: str) -> None:
        """Log a dictionary as JSON artifact."""
        import mlflow

        experiment_name = f"dict-artifact-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            mlflow.log_dict({"model": "gpt-4", "version": "1.0"}, "model_info.json")

        # Verify artifact exists
        client = mlflow.tracking.MlflowClient()
        artifacts = client.list_artifacts(run.info.run_id)
        artifact_names = [a.path for a in artifacts]
        assert "model_info.json" in artifact_names


class TestMLflowRunStatus:
    """Test run status management."""

    def test_run_status_lifecycle(self, mlflow_env: str) -> None:
        """Test run status transitions: RUNNING -> FINISHED."""
        import mlflow

        experiment_name = f"status-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            # During the run, status should be RUNNING
            current_run = mlflow.get_run(run.info.run_id)
            assert current_run.info.status == "RUNNING"

        # After context exit, status should be FINISHED
        finished_run = mlflow.get_run(run.info.run_id)
        assert finished_run.info.status == "FINISHED"

    def test_run_status_failed(self, mlflow_env: str) -> None:
        """Test marking a run as failed."""
        import mlflow

        experiment_name = f"failed-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        client = mlflow.tracking.MlflowClient()

        run = client.create_run(
            experiment_id=mlflow.get_experiment_by_name(experiment_name).experiment_id
        )

        # Mark as failed
        client.set_terminated(run.info.run_id, status="FAILED")

        # Verify status
        failed_run = mlflow.get_run(run.info.run_id)
        assert failed_run.info.status == "FAILED"


class TestMLflowTags:
    """Test run tagging functionality."""

    def test_set_tags(self, mlflow_env: str) -> None:
        """Set tags on a run."""
        import mlflow

        experiment_name = f"tags-{uuid.uuid4().hex[:8]}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            mlflow.set_tag("dataset_version", "v1.2.3")
            mlflow.set_tag("pipeline_type", "training")
            mlflow.set_tag("triggered_by", "optaic-scheduler")

        # Verify tags
        fetched_run = mlflow.get_run(run.info.run_id)
        tags = fetched_run.data.tags
        assert tags["dataset_version"] == "v1.2.3"
        assert tags["pipeline_type"] == "training"
        assert tags["triggered_by"] == "optaic-scheduler"


class TestMLflowSearchRuns:
    """Test searching for runs."""

    def test_search_by_experiment(self, mlflow_env: str) -> None:
        """Search for runs in an experiment."""
        import mlflow

        experiment_name = f"search-{uuid.uuid4().hex[:8]}"
        experiment = mlflow.set_experiment(experiment_name)

        # Create multiple runs
        run_ids = []
        for i in range(3):
            with mlflow.start_run() as run:
                mlflow.log_metric("score", i * 0.1)
                run_ids.append(run.info.run_id)

        # Search for runs
        runs = mlflow.search_runs(
            experiment_ids=[experiment.experiment_id],
            order_by=["metrics.score DESC"],
        )

        assert len(runs) == 3
        # Best score should be first (0.2)
        assert runs.iloc[0]["metrics.score"] == 0.2

    def test_search_by_filter(self, mlflow_env: str) -> None:
        """Search runs with filter expression."""
        import mlflow

        experiment_name = f"filter-{uuid.uuid4().hex[:8]}"
        experiment = mlflow.set_experiment(experiment_name)

        # Create runs with different params
        for model_type in ["linear", "neural", "tree"]:
            with mlflow.start_run():
                mlflow.log_param("model_type", model_type)
                mlflow.log_metric(
                    "accuracy", {"linear": 0.7, "neural": 0.9, "tree": 0.8}[model_type]
                )

        # Search for neural models only
        runs = mlflow.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string="params.model_type = 'neural'",
        )

        assert len(runs) == 1
        assert runs.iloc[0]["params.model_type"] == "neural"


class TestMLflowClientAPI:
    """Test using the MLflow client API directly."""

    def test_client_create_experiment(self, mlflow_env: str) -> None:
        """Use MlflowClient to create experiment."""
        import mlflow

        client = mlflow.tracking.MlflowClient()
        experiment_name = f"client-exp-{uuid.uuid4().hex[:8]}"

        experiment_id = client.create_experiment(experiment_name)
        assert experiment_id is not None

        # Verify via client
        experiment = client.get_experiment(experiment_id)
        assert experiment.name == experiment_name

    def test_client_create_run(self, mlflow_env: str) -> None:
        """Use MlflowClient to create and manage runs."""
        import mlflow

        client = mlflow.tracking.MlflowClient()
        experiment_name = f"client-run-{uuid.uuid4().hex[:8]}"

        # Create experiment first
        experiment_id = client.create_experiment(experiment_name)

        # Create run
        run = client.create_run(experiment_id)
        run_id = run.info.run_id
        assert run_id is not None
        print(f"Client-created run_id: {run_id}")

        # Log metrics via client
        client.log_metric(run_id, "accuracy", 0.88)
        client.log_param(run_id, "optimizer", "adam")

        # Terminate run
        client.set_terminated(run_id, status="FINISHED")

        # Verify
        finished_run = client.get_run(run_id)
        assert finished_run.info.status == "FINISHED"
        assert finished_run.data.metrics["accuracy"] == 0.88


class TestMLflowModelInstanceIntegration:
    """Test patterns that would be used by OptAIC ModelInstance."""

    def test_training_run_pattern(self, mlflow_env: str) -> None:
        """Simulate a training run as OptAIC would create it."""
        import mlflow

        # This simulates what a ModelInstance training flow would do
        model_instance_id = uuid.uuid4()
        dataset_instance_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        experiment_name = f"optaic/models/{model_instance_id}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run(run_name=f"training-{uuid.uuid4().hex[:8]}"):
            # Log OptAIC metadata
            mlflow.set_tag("optaic.model_instance_id", str(model_instance_id))
            mlflow.set_tag("optaic.dataset_instance_id", str(dataset_instance_id))
            mlflow.set_tag("optaic.tenant_id", str(tenant_id))
            mlflow.set_tag("optaic.run_type", "training")

            # Log training params
            mlflow.log_param("epochs", 100)
            mlflow.log_param("batch_size", 32)
            mlflow.log_param("learning_rate", 0.001)

            # Simulate training loop
            for epoch in range(10):
                mlflow.log_metric("train_loss", 1.0 - (epoch * 0.08), step=epoch)
                mlflow.log_metric("val_loss", 1.1 - (epoch * 0.07), step=epoch)

            # Log final metrics
            mlflow.log_metric("final_accuracy", 0.92)

        # Verify we can find this run by OptAIC tags
        runs = mlflow.search_runs(
            filter_string=f"tags.`optaic.model_instance_id` = '{model_instance_id}'"
        )
        assert len(runs) == 1
        assert runs.iloc[0]["tags.optaic.run_type"] == "training"

    def test_inference_run_pattern(self, mlflow_env: str) -> None:
        """Simulate an inference run as OptAIC would create it."""
        import mlflow

        model_instance_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        experiment_name = f"optaic/models/{model_instance_id}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run(run_name=f"inference-{uuid.uuid4().hex[:8]}"):
            mlflow.set_tag("optaic.model_instance_id", str(model_instance_id))
            mlflow.set_tag("optaic.tenant_id", str(tenant_id))
            mlflow.set_tag("optaic.run_type", "inference")
            mlflow.set_tag("optaic.as_of_date", "2024-01-15")

            mlflow.log_metric("inference_time_ms", 45.2)
            mlflow.log_metric("predictions_count", 1000)

        # Verify
        runs = mlflow.search_runs(
            filter_string=f"tags.`optaic.model_instance_id` = '{model_instance_id}' AND tags.`optaic.run_type` = 'inference'"
        )
        assert len(runs) == 1
