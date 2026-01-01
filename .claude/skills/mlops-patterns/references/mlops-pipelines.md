# MLOps Pipelines

Training, inference, and monitoring pipelines for ML models in OptAIC.

## Pipeline Types

| Pipeline | Input | Output | When Run |
|----------|-------|--------|----------|
| **Training** | Datasets | ModelVersion | Scheduled (weekly) or triggered |
| **Inference** | Features + Model | Predictions | Scheduled (daily) or on-demand |
| **Monitoring** | Data + Preds + Realized | Metrics + Alerts | After inference or periodically |

## Training Pipeline

### Structure

```python
# apps/api/pipelines/training_pipeline.py
from typing import TYPE_CHECKING
from uuid import UUID

from libs.core.activity import record_activity_with_outbox
from libs.core.domain.model_version import ModelVersionCreate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    import pandas as pd

class TrainingPipeline:
    """Pipeline for training ML models."""

    def __init__(
        self,
        model_instance_id: UUID,
        session: "AsyncSession",
    ):
        self.model_instance_id = model_instance_id
        self.session = session

    async def run(self, actor_id: UUID) -> "TrainingRunResult":
        """Execute training pipeline."""

        # 1. Create TrainingRun record
        run = await self._create_training_run(actor_id)

        try:
            # 2. Load model instance and definition
            instance = await self._load_model_instance()
            model_def = await self._load_model_def(instance.model_def)

            # 3. Load training data via PIT accessor
            train_data = await self._load_training_data(
                instance.training_datasets,
                instance.config.train_window,
            )

            # 4. Instantiate model and trainer
            model = model_def.create_model()
            trainer = model_def.create_trainer()

            # 5. Train
            result = trainer.train(model, train_data)

            # 6. Evaluate
            evaluator = model_def.create_evaluator()
            val_data = await self._load_validation_data(instance.training_datasets)
            predictions = model.forward(val_data.drop(columns=[instance.config.target_col]))
            metrics = evaluator.evaluate(predictions, val_data[[instance.config.target_col]])

            # 7. Create ModelVersion
            version = await self._create_model_version(
                run_id=run.id,
                artifact=result.model_artifact,
                metrics=metrics,
                hyperparams=result.hyperparams,
            )

            # 8. Update run status
            run.status = "completed"
            run.model_version_id = version.id

            # 9. Emit activity
            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="training.completed",
                payload={
                    "run_id": str(run.id),
                    "version_id": str(version.id),
                    "metrics": metrics,
                    "duration_sec": result.train_duration_sec,
                },
            )

            return TrainingRunResult(
                run_id=run.id,
                version_id=version.id,
                metrics=metrics,
                status="completed",
            )

        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)

            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="training.failed",
                payload={
                    "run_id": str(run.id),
                    "error": str(e),
                },
            )

            raise
```

### TrainingRun Model

```python
# libs/db/models/training_run.py
from sqlalchemy import Column, ForeignKey, String, Float, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from libs.db.base import Base

class TrainingRun(Base):
    """Record of a training execution."""

    __tablename__ = "training_runs"

    id = Column(UUID(as_uuid=True), primary_key=True)
    model_instance_id = Column(UUID(as_uuid=True), ForeignKey("resources.id"), nullable=False)
    model_version_id = Column(UUID(as_uuid=True), ForeignKey("model_versions.id"), nullable=True)

    status = Column(String, default="pending")  # pending, running, completed, failed
    error_message = Column(String, nullable=True)

    # Metrics
    metrics = Column(JSON, nullable=True)
    hyperparams = Column(JSON, nullable=True)
    duration_sec = Column(Float, nullable=True)

    # Lineage
    input_dataset_versions = Column(JSON, nullable=True)  # List of dataset version IDs

    # Timestamps
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
```

## Inference Pipeline

### Structure

```python
# apps/api/pipelines/inference_pipeline.py
from typing import TYPE_CHECKING
from uuid import UUID

from libs.core.activity import record_activity_with_outbox

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

class InferencePipeline:
    """Pipeline for batch inference."""

    def __init__(
        self,
        model_instance_id: UUID,
        session: "AsyncSession",
    ):
        self.model_instance_id = model_instance_id
        self.session = session

    async def run(
        self,
        actor_id: UUID,
        as_of_date: str,
    ) -> "InferenceRunResult":
        """Execute inference pipeline."""

        # 1. Create InferenceRun record
        run = await self._create_inference_run(actor_id, as_of_date)

        try:
            # 2. Load model instance and active model version
            instance = await self._load_model_instance()
            if not instance.active_model_version_id:
                raise ValueError("No active model version")

            model_version = await self._load_model_version(
                instance.active_model_version_id
            )

            # 3. Load model artifact and create predictor
            model = await self._load_model_from_artifact(model_version)
            predictor = Predictor(model)

            # 4. Load inference features via PIT accessor
            features = await self._load_inference_data(
                instance.inference_datasets,
                as_of_date=as_of_date,
            )

            # 5. Generate predictions
            predictions = predictor.predict(features)

            # 6. Validate predictions via guardrails
            await self._validate_predictions(predictions, instance)

            # 7. Write to output dataset
            dataset_version = await self._write_predictions(
                instance.output_dataset,
                predictions,
                knowledge_date=as_of_date,
            )

            # 8. Update run status
            run.status = "completed"
            run.output_version_id = dataset_version.id
            run.rows_processed = len(predictions)

            # 9. Emit activity
            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="inference.completed",
                payload={
                    "run_id": str(run.id),
                    "as_of_date": as_of_date,
                    "rows_processed": len(predictions),
                    "output_version_id": str(dataset_version.id),
                },
            )

            return InferenceRunResult(
                run_id=run.id,
                output_version_id=dataset_version.id,
                rows_processed=len(predictions),
                status="completed",
            )

        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)

            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="inference.failed",
                payload={
                    "run_id": str(run.id),
                    "as_of_date": as_of_date,
                    "error": str(e),
                },
            )

            raise
```

### PIT Correctness in Inference

```python
async def _load_inference_data(
    self,
    datasets: list[DatasetInstanceRef],
    as_of_date: str,
) -> "pd.DataFrame":
    """Load features with PIT correctness."""
    import pandas as pd

    frames = []
    for ds_ref in datasets:
        # Use PIT accessor to avoid lookahead
        data = await self.sdk.data.query(
            dataset_id=ds_ref.dataset_id,
            as_of_date=as_of_date,
            knowledge_date=as_of_date,  # Critical: knowledge_date = as_of_date
        )
        frames.append(data)

    # Merge on common index
    result = frames[0]
    for frame in frames[1:]:
        result = result.join(frame, how="inner")

    return result
```

## Monitoring Pipeline

### Structure

```python
# apps/api/pipelines/monitoring_pipeline.py
from typing import TYPE_CHECKING
from uuid import UUID

from libs.core.activity import record_activity_with_outbox

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

class MonitoringPipeline:
    """Pipeline for data and performance monitoring."""

    def __init__(
        self,
        model_instance_id: UUID,
        session: "AsyncSession",
    ):
        self.model_instance_id = model_instance_id
        self.session = session

    async def run(
        self,
        actor_id: UUID,
        as_of_date: str,
    ) -> "MonitoringRunResult":
        """Execute monitoring pipeline."""

        # 1. Load model instance and monitors
        instance = await self._load_model_instance()
        model_def = await self._load_model_def(instance.model_def)

        data_monitor = model_def.create_data_monitor()
        perf_monitor = model_def.create_performance_monitor()

        # 2. Run data drift check
        current_features = await self._load_current_features(
            instance.inference_datasets,
            as_of_date,
        )
        drift_report = data_monitor.check_drift(current_features)

        # 3. Run performance check (if realized data available)
        perf_report = None
        predictions = await self._load_predictions(instance.output_dataset, as_of_date)
        realized = await self._load_realized(as_of_date)

        if realized is not None:
            perf_report = perf_monitor.check_degradation(predictions, realized)

        # 4. Create MonitoringRun record
        run = await self._create_monitoring_run(
            actor_id=actor_id,
            as_of_date=as_of_date,
            drift_report=drift_report,
            perf_report=perf_report,
        )

        # 5. Emit alerts if needed
        if drift_report.has_drift:
            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="monitoring.drift_alert",
                payload={
                    "run_id": str(run.id),
                    "drift_scores": drift_report.drift_scores,
                    "threshold": drift_report.threshold,
                },
            )

        if perf_report and perf_report.is_degraded:
            await record_activity_with_outbox(
                session=self.session,
                actor_id=actor_id,
                resource_id=self.model_instance_id,
                action="monitoring.performance_alert",
                payload={
                    "run_id": str(run.id),
                    "degradation_pct": perf_report.degradation_pct,
                    "realized_metrics": perf_report.realized_metrics,
                },
            )

        return MonitoringRunResult(
            run_id=run.id,
            drift_report=drift_report,
            perf_report=perf_report,
        )
```

## Pipeline Orchestration

### With Prefect

```python
# apps/worker/flows/mlops_flows.py
from prefect import flow, task
from uuid import UUID

@task
async def train_model_task(model_instance_id: UUID, actor_id: UUID):
    """Prefect task for training."""
    from apps.api.pipelines.training_pipeline import TrainingPipeline

    async with get_session() as session:
        pipeline = TrainingPipeline(model_instance_id, session)
        return await pipeline.run(actor_id)

@task
async def inference_task(model_instance_id: UUID, actor_id: UUID, as_of_date: str):
    """Prefect task for inference."""
    from apps.api.pipelines.inference_pipeline import InferencePipeline

    async with get_session() as session:
        pipeline = InferencePipeline(model_instance_id, session)
        return await pipeline.run(actor_id, as_of_date)

@flow
async def mlops_daily_flow(model_instance_id: UUID, actor_id: UUID, as_of_date: str):
    """Daily MLOps workflow: inference + monitoring."""

    # Run inference
    inference_result = await inference_task(model_instance_id, actor_id, as_of_date)

    # Run monitoring
    monitoring_result = await monitoring_task(model_instance_id, actor_id, as_of_date)

    return {
        "inference": inference_result,
        "monitoring": monitoring_result,
    }

@flow
async def mlops_weekly_flow(model_instance_id: UUID, actor_id: UUID):
    """Weekly MLOps workflow: training + activation."""

    # Run training
    training_result = await train_model_task(model_instance_id, actor_id)

    # Optionally auto-activate if metrics pass threshold
    if training_result.metrics.get("ic", 0) > 0.05:
        await activate_model_version_task(
            model_instance_id,
            training_result.version_id,
            actor_id,
        )

    return training_result
```

## Lineage Tracking

All pipeline runs create lineage edges:

```
TrainingRun
├── inputs: [DatasetVersion_A, DatasetVersion_B]
└── outputs: [ModelVersion_X]

InferenceRun
├── inputs: [DatasetVersion_C, ModelVersion_X]
└── outputs: [DatasetVersion_D (predictions)]

MonitoringRun
├── inputs: [DatasetVersion_D, DatasetVersion_E (realized)]
└── outputs: [MetricsRecord]
```

This enables full provenance tracking from features → model → predictions → performance.
