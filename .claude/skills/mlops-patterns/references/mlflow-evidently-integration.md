# MLflow + Evidently Integration Patterns

OptAIC uses MLflow for experiment tracking/model registry and Evidently for monitoring/evaluation.

## Tech Stack Division

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        OptAIC MLOps Tech Stack                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────┐   │
│  │         MLflow              │  │         Evidently               │   │
│  │  (Experiment & Registry)    │  │  (Monitoring & Evaluation)      │   │
│  ├─────────────────────────────┤  ├─────────────────────────────────┤   │
│  │  • Experiment tracking      │  │  • Data drift detection         │   │
│  │  • Parameter logging        │  │  • Model performance monitoring │   │
│  │  • Metric logging           │  │  • Data quality reports         │   │
│  │  • Artifact storage         │  │  • Test suites for CI/CD        │   │
│  │  • Model registry           │  │  • Real-time monitors           │   │
│  │  • Model versioning         │  │  • HTML/JSON reports            │   │
│  └─────────────────────────────┘  └─────────────────────────────────┘   │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Optional: WhyLogs                             │    │
│  │  • Lightweight data profiling                                    │    │
│  │  • Statistical summaries per batch                               │    │
│  │  • Low-overhead logging                                          │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## MLflow Integration

### 1. Experiment Tracking in Training Pipeline

```python
# libs/core/adapters/mlflow_adapter.py
from typing import TYPE_CHECKING
from contextlib import asynccontextmanager

if TYPE_CHECKING:
    import mlflow
    import pandas as pd

class MLflowAdapter:
    """Adapter for MLflow experiment tracking and model registry."""

    def __init__(self, tracking_uri: str, experiment_name: str | None = None):
        import mlflow
        mlflow.set_tracking_uri(tracking_uri)
        self.experiment_name = experiment_name

    @asynccontextmanager
    async def start_run(
        self,
        run_name: str,
        tags: dict | None = None,
    ):
        """Context manager for MLflow run."""
        import mlflow

        if self.experiment_name:
            mlflow.set_experiment(self.experiment_name)

        with mlflow.start_run(run_name=run_name, tags=tags) as run:
            yield run

    async def log_training(
        self,
        params: dict,
        metrics: dict,
        artifacts: dict[str, bytes] | None = None,
        model: "Any" = None,
        model_signature: "Any" = None,
    ):
        """Log training run to MLflow."""
        import mlflow

        # Log parameters
        mlflow.log_params(params)

        # Log metrics
        mlflow.log_metrics(metrics)

        # Log artifacts
        if artifacts:
            import tempfile
            import os

            with tempfile.TemporaryDirectory() as tmpdir:
                for name, data in artifacts.items():
                    path = os.path.join(tmpdir, name)
                    with open(path, "wb") as f:
                        f.write(data)
                    mlflow.log_artifact(path)

        # Log model
        if model is not None:
            mlflow.sklearn.log_model(model, "model", signature=model_signature)

    async def register_model(
        self,
        model_uri: str,
        name: str,
        tags: dict | None = None,
    ) -> str:
        """Register model in MLflow registry."""
        import mlflow

        result = mlflow.register_model(model_uri, name)

        if tags:
            client = mlflow.tracking.MlflowClient()
            for key, value in tags.items():
                client.set_model_version_tag(name, result.version, key, value)

        return result.version

    async def transition_model_stage(
        self,
        name: str,
        version: str,
        stage: str,  # "Staging", "Production", "Archived"
    ):
        """Transition model to new stage."""
        import mlflow

        client = mlflow.tracking.MlflowClient()
        client.transition_model_version_stage(
            name=name,
            version=version,
            stage=stage,
        )

    async def load_model(self, model_uri: str) -> "Any":
        """Load model from MLflow."""
        import mlflow

        return mlflow.sklearn.load_model(model_uri)
```

### 2. Training Pipeline with MLflow

```python
# apps/api/pipelines/training_pipeline.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.core.adapters.mlflow_adapter import MLflowAdapter

class TrainingPipeline:
    """Training pipeline with MLflow integration."""

    def __init__(
        self,
        model_instance_id: UUID,
        session: "AsyncSession",
        mlflow_adapter: "MLflowAdapter | None" = None,
    ):
        self.model_instance_id = model_instance_id
        self.session = session
        self.mlflow_adapter = mlflow_adapter

    async def run(self, actor_id: UUID) -> "TrainingRunResult":
        """Execute training with MLflow tracking."""

        instance = await self._load_model_instance()
        run_name = f"{instance.name}_train_{datetime.utcnow().isoformat()}"

        # Track with MLflow if enabled
        if self.mlflow_adapter:
            async with self.mlflow_adapter.start_run(
                run_name=run_name,
                tags={
                    "optaic_instance_id": str(self.model_instance_id),
                    "optaic_def_version": instance.model_def.def_version,
                },
            ) as mlflow_run:
                result = await self._train(instance)

                # Log to MLflow
                await self.mlflow_adapter.log_training(
                    params=result.hyperparams,
                    metrics=result.metrics,
                    model=result.model,
                )

                # Register model
                model_uri = f"runs:/{mlflow_run.info.run_id}/model"
                mlflow_version = await self.mlflow_adapter.register_model(
                    model_uri=model_uri,
                    name=instance.name,
                    tags={"optaic_version_id": str(result.version_id)},
                )

                result.mlflow_run_id = mlflow_run.info.run_id
                result.mlflow_version = mlflow_version
        else:
            result = await self._train(instance)

        return result
```

## Evidently Integration

### 1. Evidently Adapter

```python
# libs/core/adapters/evidently_adapter.py
from typing import TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    import pandas as pd
    from evidently.report import Report
    from evidently.test_suite import TestSuite

class EvidentlyAdapter:
    """Adapter for Evidently monitoring and evaluation."""

    def __init__(self, reports_dir: Path | None = None):
        self.reports_dir = reports_dir or Path("DATA_DIR/evidently/reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    async def create_data_drift_report(
        self,
        reference_data: "pd.DataFrame",
        current_data: "pd.DataFrame",
        column_mapping: dict | None = None,
    ) -> "DataDriftResult":
        """Generate data drift report."""
        from evidently.report import Report
        from evidently.metric_preset import DataDriftPreset
        from evidently import ColumnMapping

        mapping = ColumnMapping(**column_mapping) if column_mapping else None

        report = Report(metrics=[DataDriftPreset()])
        report.run(
            reference_data=reference_data,
            current_data=current_data,
            column_mapping=mapping,
        )

        # Extract drift results
        result_dict = report.as_dict()
        drift_metrics = result_dict["metrics"][0]["result"]

        return DataDriftResult(
            dataset_drift=drift_metrics["dataset_drift"],
            drift_share=drift_metrics["drift_share"],
            number_of_columns=drift_metrics["number_of_columns"],
            number_of_drifted_columns=drift_metrics["number_of_drifted_columns"],
            drifted_columns=self._extract_drifted_columns(drift_metrics),
            report_html=report.get_html(),
        )

    async def create_model_performance_report(
        self,
        reference_data: "pd.DataFrame",
        current_data: "pd.DataFrame",
        target_col: str,
        prediction_col: str,
    ) -> "PerformanceResult":
        """Generate model performance report for regression."""
        from evidently.report import Report
        from evidently.metric_preset import RegressionPreset
        from evidently import ColumnMapping

        mapping = ColumnMapping(
            target=target_col,
            prediction=prediction_col,
        )

        report = Report(metrics=[RegressionPreset()])
        report.run(
            reference_data=reference_data,
            current_data=current_data,
            column_mapping=mapping,
        )

        result_dict = report.as_dict()

        return PerformanceResult(
            metrics=self._extract_regression_metrics(result_dict),
            report_html=report.get_html(),
        )

    async def create_classification_report(
        self,
        reference_data: "pd.DataFrame",
        current_data: "pd.DataFrame",
        target_col: str,
        prediction_col: str,
    ) -> "PerformanceResult":
        """Generate model performance report for classification."""
        from evidently.report import Report
        from evidently.metric_preset import ClassificationPreset
        from evidently import ColumnMapping

        mapping = ColumnMapping(
            target=target_col,
            prediction=prediction_col,
        )

        report = Report(metrics=[ClassificationPreset()])
        report.run(
            reference_data=reference_data,
            current_data=current_data,
            column_mapping=mapping,
        )

        return PerformanceResult(
            metrics=self._extract_classification_metrics(report.as_dict()),
            report_html=report.get_html(),
        )

    async def run_test_suite(
        self,
        reference_data: "pd.DataFrame",
        current_data: "pd.DataFrame",
        tests: list[str] | None = None,
    ) -> "TestSuiteResult":
        """Run Evidently test suite for CI/CD validation."""
        from evidently.test_suite import TestSuite
        from evidently.test_preset import (
            DataDriftTestPreset,
            DataQualityTestPreset,
            DataStabilityTestPreset,
        )

        # Default test presets
        test_presets = [
            DataDriftTestPreset(),
            DataQualityTestPreset(),
            DataStabilityTestPreset(),
        ]

        suite = TestSuite(tests=test_presets)
        suite.run(reference_data=reference_data, current_data=current_data)

        result_dict = suite.as_dict()

        return TestSuiteResult(
            success=result_dict["summary"]["all_passed"],
            total_tests=result_dict["summary"]["total"],
            passed_tests=result_dict["summary"]["success"],
            failed_tests=result_dict["summary"]["failed"],
            test_results=result_dict["tests"],
            report_html=suite.get_html(),
        )

    async def save_report(
        self,
        report_html: str,
        report_type: str,
        model_instance_id: str,
        as_of_date: str,
    ) -> Path:
        """Save HTML report to disk."""
        filename = f"{model_instance_id}_{report_type}_{as_of_date}.html"
        path = self.reports_dir / filename
        path.write_text(report_html)
        return path

    def _extract_drifted_columns(self, drift_metrics: dict) -> list[dict]:
        """Extract list of drifted columns with scores."""
        drifted = []
        for col, data in drift_metrics.get("drift_by_columns", {}).items():
            if data.get("drift_detected"):
                drifted.append({
                    "column": col,
                    "drift_score": data.get("drift_score"),
                    "stattest_name": data.get("stattest_name"),
                })
        return drifted
```

### 2. Monitoring Pipeline with Evidently

```python
# apps/api/pipelines/monitoring_pipeline.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.core.adapters.evidently_adapter import EvidentlyAdapter

class MonitoringPipeline:
    """Monitoring pipeline with Evidently integration."""

    def __init__(
        self,
        model_instance_id: UUID,
        session: "AsyncSession",
        evidently_adapter: "EvidentlyAdapter",
    ):
        self.model_instance_id = model_instance_id
        self.session = session
        self.evidently = evidently_adapter

    async def run(
        self,
        actor_id: UUID,
        as_of_date: str,
    ) -> "MonitoringRunResult":
        """Execute monitoring with Evidently."""

        instance = await self._load_model_instance()

        # Load reference data (from training)
        reference_data = await self._load_reference_data(instance)

        # Load current data
        current_features = await self._load_current_features(
            instance.inference_datasets, as_of_date
        )

        # 1. Data Drift Report
        drift_result = await self.evidently.create_data_drift_report(
            reference_data=reference_data,
            current_data=current_features,
        )

        # Save drift report
        drift_report_path = await self.evidently.save_report(
            report_html=drift_result.report_html,
            report_type="data_drift",
            model_instance_id=str(self.model_instance_id),
            as_of_date=as_of_date,
        )

        # 2. Performance Report (if realized data available)
        perf_result = None
        predictions = await self._load_predictions(instance.output_dataset, as_of_date)
        realized = await self._load_realized(as_of_date)

        if realized is not None:
            # Merge predictions with realized
            merged = predictions.join(realized, how="inner")

            perf_result = await self.evidently.create_model_performance_report(
                reference_data=reference_data,
                current_data=merged,
                target_col="realized_return",
                prediction_col="signal",
            )

            # Save performance report
            await self.evidently.save_report(
                report_html=perf_result.report_html,
                report_type="performance",
                model_instance_id=str(self.model_instance_id),
                as_of_date=as_of_date,
            )

        # 3. Create monitoring run record
        run = await self._create_monitoring_run(
            actor_id=actor_id,
            as_of_date=as_of_date,
            drift_result=drift_result,
            perf_result=perf_result,
            drift_report_path=str(drift_report_path),
        )

        # 4. Emit alerts if thresholds exceeded
        if drift_result.dataset_drift:
            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="monitoring.drift_alert",
                payload={
                    "run_id": str(run.id),
                    "drift_share": drift_result.drift_share,
                    "drifted_columns": drift_result.drifted_columns,
                    "report_path": str(drift_report_path),
                },
            )

        return MonitoringRunResult(
            run_id=run.id,
            drift_result=drift_result,
            perf_result=perf_result,
        )
```

### 3. CI/CD Validation with Evidently Test Suites

```python
# libs/core/validation/model_validation.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.core.adapters.evidently_adapter import EvidentlyAdapter

class ModelValidator:
    """Validate model data quality before training/inference."""

    def __init__(self, evidently: "EvidentlyAdapter"):
        self.evidently = evidently

    async def validate_training_data(
        self,
        train_data: "pd.DataFrame",
        reference_data: "pd.DataFrame | None" = None,
    ) -> "ValidationResult":
        """Validate training data quality."""
        from evidently.test_suite import TestSuite
        from evidently.tests import (
            TestNumberOfColumnsWithMissingValues,
            TestNumberOfRowsWithMissingValues,
            TestNumberOfConstantColumns,
            TestNumberOfDuplicatedRows,
            TestNumberOfDuplicatedColumns,
            TestColumnsType,
            TestNumberOfRows,
        )

        tests = [
            TestNumberOfColumnsWithMissingValues(lte=5),
            TestNumberOfRowsWithMissingValues(lte=0.1),  # Max 10% missing
            TestNumberOfConstantColumns(eq=0),
            TestNumberOfDuplicatedRows(lte=0.01),  # Max 1% duplicates
            TestNumberOfRows(gte=1000),  # Min 1000 rows
        ]

        suite = TestSuite(tests=tests)

        if reference_data is not None:
            suite.run(reference_data=reference_data, current_data=train_data)
        else:
            suite.run(current_data=train_data)

        result = suite.as_dict()

        return ValidationResult(
            passed=result["summary"]["all_passed"],
            issues=self._extract_failed_tests(result),
        )

    async def validate_before_inference(
        self,
        features: "pd.DataFrame",
        reference_schema: dict,
    ) -> "ValidationResult":
        """Validate inference data matches expected schema."""
        from evidently.test_suite import TestSuite
        from evidently.tests import (
            TestColumnShareOfMissingValues,
            TestColumnNumberOfMissingValues,
        )

        # Check each expected column
        tests = []
        for col, config in reference_schema.items():
            tests.append(
                TestColumnShareOfMissingValues(
                    column_name=col,
                    lte=config.get("max_missing_share", 0.05),
                )
            )

        suite = TestSuite(tests=tests)
        suite.run(current_data=features)

        result = suite.as_dict()

        return ValidationResult(
            passed=result["summary"]["all_passed"],
            issues=self._extract_failed_tests(result),
        )
```

## Combined Workflow Example

```python
# Full training workflow with MLflow + Evidently
async def train_model_workflow(
    model_instance_id: UUID,
    actor_id: UUID,
    mlflow_adapter: MLflowAdapter,
    evidently_adapter: EvidentlyAdapter,
):
    """Complete training workflow."""

    # 1. Load and validate training data
    train_data = await load_training_data(model_instance_id)

    validator = ModelValidator(evidently_adapter)
    validation = await validator.validate_training_data(train_data)

    if not validation.passed:
        raise ValueError(f"Training data validation failed: {validation.issues}")

    # 2. Train with MLflow tracking
    pipeline = TrainingPipeline(
        model_instance_id=model_instance_id,
        session=session,
        mlflow_adapter=mlflow_adapter,
    )
    result = await pipeline.run(actor_id)

    # 3. Run initial monitoring to establish baseline
    monitoring = MonitoringPipeline(
        model_instance_id=model_instance_id,
        session=session,
        evidently_adapter=evidently_adapter,
    )
    await monitoring.run(actor_id, as_of_date=datetime.utcnow().isoformat())

    return result
```

## Embedded Mode Configuration

```python
# optaic/server.py
class OptAICServer:
    """Server with MLflow + Evidently in embedded mode."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.mlflow_adapter = None
        self.evidently_adapter = None

    async def start(self):
        """Start server with optional MLflow."""

        # Always initialize Evidently (no server needed)
        self.evidently_adapter = EvidentlyAdapter(
            reports_dir=self.config.data_dir / "evidently" / "reports"
        )

        # Optionally start MLflow server
        if self.config.with_mlflow:
            mlflow_db = self.config.data_dir / "mlflow" / "mlflow.db"
            mlflow_artifacts = self.config.data_dir / "mlflow" / "artifacts"

            # Start MLflow server subprocess
            self.mlflow_process = await self._start_mlflow_server(
                backend_store_uri=f"sqlite:///{mlflow_db}",
                artifact_root=str(mlflow_artifacts),
                port=5000,
            )

            self.mlflow_adapter = MLflowAdapter(
                tracking_uri="http://localhost:5000"
            )
```

## Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
mlops = [
    "mlflow>=2.10.0",
    "evidently>=0.4.0",
    "whylogs>=1.3.0",  # Optional: lightweight profiling
]
```

## Summary

| Component | Tool | Purpose | Integration |
|-----------|------|---------|-------------|
| Experiment Tracking | MLflow | Log params, metrics, artifacts | TrainingPipeline |
| Model Registry | MLflow | Version management, stage transitions | ModelVersionService |
| Data Drift | Evidently | Detect feature distribution changes | MonitoringPipeline |
| Model Performance | Evidently | Track prediction accuracy over time | MonitoringPipeline |
| Data Validation | Evidently Test Suites | CI/CD quality gates | ModelValidator |
| Reports | Evidently | HTML reports for debugging | Saved to DATA_DIR |
