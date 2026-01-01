# Unified ML SDK (`optaic.mlops`)

Patterns for implementing and using the unified ML SDK that wraps MLOps infrastructure.

## Overview

The `optaic.mlops` SDK provides a unified interface for ML development, wrapping MLflow, Evidently, and Prefect into cohesive modules. Users write models with native ML libraries while the SDK handles infrastructure.

```
optaic.mlops
├── tracking      # Experiment tracking (MLflow)
├── registry      # Model versioning (MLflow Model Registry)
├── monitoring    # Drift & performance (Evidently)
├── pipeline      # Orchestration (Prefect)
├── data          # PIT-aware data access
└── base          # Base classes for definitions
```

## Module: `optaic.mlops.tracking`

Wraps MLflow experiment tracking with OptAIC governance integration.

```python
# optaic/mlops/tracking.py
from typing import Any
from functools import wraps
import mlflow

from optaic.mlops._config import get_tracking_uri


def _ensure_experiment(name: str) -> str:
    """Get or create MLflow experiment."""
    mlflow.set_tracking_uri(get_tracking_uri())
    experiment = mlflow.get_experiment_by_name(name)
    if experiment is None:
        return mlflow.create_experiment(name)
    return experiment.experiment_id


def log_params(params: dict[str, Any]) -> None:
    """Log parameters to active run."""
    mlflow.log_params(params)


def log_metrics(metrics: dict[str, float], step: int | None = None) -> None:
    """Log metrics to active run."""
    mlflow.log_metrics(metrics, step=step)


def log_artifacts(local_path: str, artifact_path: str | None = None) -> None:
    """Log artifacts to active run."""
    mlflow.log_artifacts(local_path, artifact_path)


def autolog(framework: str = "auto"):
    """
    Decorator for automatic logging.

    Usage:
        @tracking.autolog()
        def train(self, model, data):
            model.fit(X, y)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Enable framework autologging
            if framework == "auto":
                mlflow.autolog()
            elif framework == "sklearn":
                mlflow.sklearn.autolog()
            elif framework == "xgboost":
                mlflow.xgboost.autolog()
            elif framework == "pytorch":
                mlflow.pytorch.autolog()

            with mlflow.start_run(nested=True):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator


class TrackingContext:
    """Context manager for tracking runs."""

    def __init__(
        self,
        experiment_name: str,
        run_name: str | None = None,
        tags: dict[str, str] | None = None,
    ):
        self.experiment_name = experiment_name
        self.run_name = run_name
        self.tags = tags or {}
        self._run = None

    def __enter__(self):
        experiment_id = _ensure_experiment(self.experiment_name)
        self._run = mlflow.start_run(
            experiment_id=experiment_id,
            run_name=self.run_name,
            tags=self.tags,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        mlflow.end_run()
        return False

    @property
    def run_id(self) -> str:
        return self._run.info.run_id
```

## Module: `optaic.mlops.registry`

Wraps MLflow Model Registry with stage management.

```python
# optaic/mlops/registry.py
from typing import Any
import mlflow
from mlflow.tracking import MlflowClient

from optaic.mlops._config import get_tracking_uri


def _get_client() -> MlflowClient:
    return MlflowClient(tracking_uri=get_tracking_uri())


def register_model(
    model: Any,
    name: str,
    metrics: dict[str, float] | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    """
    Register model to registry.

    Returns model URI for loading.
    """
    # Log model to MLflow
    model_info = mlflow.sklearn.log_model(model, "model")

    # Register to model registry
    client = _get_client()
    result = client.create_model_version(
        name=name,
        source=model_info.model_uri,
        run_id=mlflow.active_run().info.run_id,
        tags=tags,
    )

    # Log metrics if provided
    if metrics:
        for key, value in metrics.items():
            client.set_model_version_tag(
                name=name,
                version=result.version,
                key=f"metric.{key}",
                value=str(value),
            )

    return f"models:/{name}/{result.version}"


def load_model(model_uri: str) -> Any:
    """Load model from registry."""
    return mlflow.pyfunc.load_model(model_uri)


def get_latest_version(
    name: str,
    stage: str = "Production",
) -> str:
    """Get latest model version URI for given stage."""
    client = _get_client()
    versions = client.get_latest_versions(name, stages=[stage])
    if not versions:
        raise ValueError(f"No {stage} version found for {name}")
    return f"models:/{name}/{versions[0].version}"


def transition_stage(
    name: str,
    version: str,
    stage: str,
    archive_existing: bool = True,
) -> None:
    """Transition model version to new stage."""
    client = _get_client()
    client.transition_model_version_stage(
        name=name,
        version=version,
        stage=stage,
        archive_existing_versions=archive_existing,
    )
```

## Module: `optaic.mlops.monitoring`

Wraps Evidently for data drift and performance monitoring.

```python
# optaic/mlops/monitoring.py
from typing import Any
import pandas as pd
from evidently import ColumnMapping
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset, RegressionPreset
from evidently.test_suite import TestSuite
from evidently.tests import *


class DataDriftMonitor:
    """Monitor feature distribution drift."""

    def __init__(
        self,
        reference_data: pd.DataFrame,
        column_mapping: ColumnMapping | None = None,
    ):
        self.reference_data = reference_data
        self.column_mapping = column_mapping or ColumnMapping()

    def check(self, current_data: pd.DataFrame) -> dict[str, Any]:
        """Run drift check and return results."""
        report = Report(metrics=[DataDriftPreset()])
        report.run(
            reference_data=self.reference_data,
            current_data=current_data,
            column_mapping=self.column_mapping,
        )
        return report.as_dict()

    def save_report(self, current_data: pd.DataFrame, path: str) -> None:
        """Save HTML drift report."""
        report = Report(metrics=[DataDriftPreset()])
        report.run(
            reference_data=self.reference_data,
            current_data=current_data,
            column_mapping=self.column_mapping,
        )
        report.save_html(path)


class PerformanceMonitor:
    """Monitor model performance over time."""

    def __init__(
        self,
        reference_data: pd.DataFrame,
        target_col: str,
        prediction_col: str,
    ):
        self.reference_data = reference_data
        self.column_mapping = ColumnMapping(
            target=target_col,
            prediction=prediction_col,
        )

    def check(self, current_data: pd.DataFrame) -> dict[str, Any]:
        """Run performance check."""
        report = Report(metrics=[RegressionPreset()])
        report.run(
            reference_data=self.reference_data,
            current_data=current_data,
            column_mapping=self.column_mapping,
        )
        return report.as_dict()


def validate_signal_bounds(
    signals: pd.Series,
    min: float = -1.0,
    max: float = 1.0,
) -> None:
    """Validate signal values are within bounds."""
    if signals.min() < min or signals.max() > max:
        raise ValueError(
            f"Signal values out of bounds [{min}, {max}]: "
            f"min={signals.min()}, max={signals.max()}"
        )


def validate_no_lookahead(
    df: pd.DataFrame,
    knowledge_date_col: str,
    as_of_date: str,
) -> None:
    """Validate no data from future of as_of_date."""
    future_data = df[df[knowledge_date_col] > as_of_date]
    if len(future_data) > 0:
        raise ValueError(
            f"Lookahead detected: {len(future_data)} rows have "
            f"knowledge_date > as_of_date ({as_of_date})"
        )


def validate_data_quality(
    df: pd.DataFrame,
    schema: dict[str, type],
    allow_nulls: bool = False,
) -> None:
    """Validate data against expected schema."""
    for col, dtype in schema.items():
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")
        if not allow_nulls and df[col].isna().any():
            raise ValueError(f"Null values in column: {col}")
```

## Module: `optaic.mlops.pipeline`

Wraps Prefect for workflow orchestration.

```python
# optaic/mlops/pipeline.py
from typing import Callable, Any
from functools import wraps

from optaic.mlops._config import get_orchestrator_mode


# Conditional import based on mode
_prefect_available = False
try:
    from prefect import task as prefect_task, flow as prefect_flow
    from prefect.deployments import Deployment
    _prefect_available = True
except ImportError:
    pass


def task(func: Callable = None, **kwargs):
    """
    Decorator for pipeline tasks.

    In Prefect mode: wraps with prefect.task
    In local mode: runs function directly
    """
    def decorator(fn):
        if get_orchestrator_mode() == "prefect" and _prefect_available:
            return prefect_task(fn, **kwargs)

        @wraps(fn)
        def wrapper(*args, **kw):
            return fn(*args, **kw)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def flow(func: Callable = None, **kwargs):
    """
    Decorator for pipeline flows.

    In Prefect mode: wraps with prefect.flow
    In local mode: runs function directly
    """
    def decorator(fn):
        if get_orchestrator_mode() == "prefect" and _prefect_available:
            return prefect_flow(fn, **kwargs)

        @wraps(fn)
        def wrapper(*args, **kw):
            return fn(*args, **kw)
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def schedule(
    flow_func: Callable,
    cron: str,
    name: str | None = None,
) -> None:
    """Schedule a flow with cron expression."""
    if get_orchestrator_mode() == "prefect" and _prefect_available:
        from prefect.server.schemas.schedules import CronSchedule

        deployment = Deployment.build_from_flow(
            flow=flow_func,
            name=name or flow_func.__name__,
            schedule=CronSchedule(cron=cron),
        )
        deployment.apply()
    else:
        # Local mode: use APScheduler
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            flow_func,
            CronTrigger.from_crontab(cron),
            id=name or flow_func.__name__,
        )
        scheduler.start()


def run_now(flow_func: Callable, *args, **kwargs) -> Any:
    """Run a flow immediately."""
    return flow_func(*args, **kwargs)
```

## Module: `optaic.mlops.data`

PIT-aware data access layer.

```python
# optaic/mlops/data.py
from typing import Any
from dataclasses import dataclass
import pandas as pd

from libs.db.engine import get_session
from apps.api.services.dataset_service import DatasetService


@dataclass
class DatasetRef:
    """Reference to a dataset instance."""
    name: str
    version: str | None = None  # None = latest


async def load_dataset(
    ref: DatasetRef | str,
    as_of: str | None = None,
) -> pd.DataFrame:
    """
    Load dataset with PIT-correct filtering.

    Args:
        ref: Dataset reference (name or DatasetRef)
        as_of: As-of date for PIT query (default: now)

    Returns:
        DataFrame with data available as of the given date
    """
    if isinstance(ref, str):
        ref = DatasetRef(name=ref)

    async with get_session() as session:
        service = DatasetService(session)
        return await service.load_pit(
            name=ref.name,
            version=ref.version,
            as_of=as_of,
        )


async def write_dataset(
    df: pd.DataFrame,
    name: str,
    knowledge_date: str,
    schema: dict[str, type] | None = None,
) -> str:
    """
    Write dataset with knowledge_date stamp.

    Returns new version ID.
    """
    async with get_session() as session:
        service = DatasetService(session)
        return await service.write_version(
            name=name,
            data=df,
            knowledge_date=knowledge_date,
            schema=schema,
        )
```

## Module: `optaic.mlops.base`

Base classes for ML model definitions.

```python
# optaic/mlops/base.py
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar
import pandas as pd

T = TypeVar("T")


class BaseModel(ABC):
    """Base class for ML models."""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train the model."""
        pass

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Generate predictions."""
        pass

    def get_params(self) -> dict[str, Any]:
        """Return model parameters for logging."""
        return {}


class BaseTrainer(ABC, Generic[T]):
    """Base class for model trainers."""

    def __init__(
        self,
        model_instance_name: str,
        as_of_date: str,
        config: dict[str, Any] | None = None,
    ):
        self.model_instance_name = model_instance_name
        self.as_of_date = as_of_date
        self.config = config or {}

    @abstractmethod
    def train(self, model: T, train_data: Any) -> str:
        """
        Train model and return model URI.

        Should use tracking.autolog() decorator.
        """
        pass

    def compute_ic(self, y_true: pd.Series, y_pred: pd.Series) -> float:
        """Compute information coefficient (rank correlation)."""
        return y_true.corr(y_pred, method="spearman")


class BasePredictor(ABC, Generic[T]):
    """Base class for model predictors."""

    def __init__(self, model: T):
        self.model = model

    @abstractmethod
    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Generate predictions."""
        pass

    @abstractmethod
    def predict_batch(
        self,
        features: pd.DataFrame,
        batch_size: int = 10000,
    ) -> pd.Series:
        """Generate predictions in batches."""
        pass


class BaseMonitor(ABC):
    """Base class for model monitors."""

    @abstractmethod
    def check_data_drift(self, current_data: pd.DataFrame) -> dict[str, Any]:
        """Check for input data drift."""
        pass

    @abstractmethod
    def check_performance(self, predictions: pd.DataFrame) -> dict[str, Any]:
        """Check model performance."""
        pass
```

## Configuration

```python
# optaic/mlops/_config.py
import os
from functools import lru_cache


@lru_cache
def get_tracking_uri() -> str:
    """Get MLflow tracking URI based on mode."""
    return os.getenv(
        "MLFLOW_TRACKING_URI",
        f"sqlite:///{os.getenv('DATA_DIR', 'data')}/mlflow/mlflow.db"
    )


@lru_cache
def get_orchestrator_mode() -> str:
    """Get orchestrator mode: 'prefect' or 'local'."""
    return os.getenv("OPTAIC_ORCHESTRATOR", "local")


@lru_cache
def get_artifact_root() -> str:
    """Get artifact storage root."""
    return os.getenv(
        "MLFLOW_ARTIFACT_ROOT",
        f"{os.getenv('DATA_DIR', 'data')}/mlflow/artifacts"
    )
```

## Complete Example

```python
from optaic.mlops import tracking, registry, monitoring, pipeline
from optaic.mlops.base import BaseModel, BaseTrainer
from optaic.mlops.data import load_dataset, write_dataset, DatasetRef

import xgboost as xgb
import pandas as pd


class XGBSignalModel(BaseModel):
    """XGBoost signal generation model."""

    def __init__(self, **params):
        self.params = params
        self.model = xgb.XGBRegressor(**params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self.model.fit(X, y)

    def predict(self, X: pd.DataFrame) -> pd.Series:
        return pd.Series(self.model.predict(X), index=X.index)

    def get_params(self) -> dict:
        return self.params


class XGBSignalTrainer(BaseTrainer[XGBSignalModel]):
    """Trainer for XGB signal models."""

    @tracking.autolog(framework="xgboost")
    async def train(
        self,
        model: XGBSignalModel,
        train_data: DatasetRef,
    ) -> str:
        # Load PIT-correct data
        df = await load_dataset(train_data, as_of=self.as_of_date)

        # Validate no lookahead
        monitoring.validate_no_lookahead(
            df,
            knowledge_date_col="knowledge_date",
            as_of_date=self.as_of_date,
        )

        # Prepare features and target
        target_col = self.config.get("target_col", "fwd_return_5d")
        feature_cols = [c for c in df.columns if c not in [target_col, "knowledge_date", "date"]]

        X = df[feature_cols]
        y = df[target_col]

        # Train
        model.fit(X, y)

        # Validate outputs
        preds = model.predict(X)
        monitoring.validate_signal_bounds(preds, min=-1, max=1)

        # Register model
        ic = self.compute_ic(y, preds)
        model_uri = registry.register_model(
            model=model.model,  # The underlying XGBRegressor
            name=self.model_instance_name,
            metrics={"ic": ic, "train_samples": len(y)},
        )

        return model_uri


# Pipeline definition
@pipeline.task
async def load_features(dataset_name: str, as_of: str):
    return await load_dataset(DatasetRef(dataset_name), as_of=as_of)


@pipeline.task
async def train_signal_model(
    model_name: str,
    features: pd.DataFrame,
    as_of: str,
    config: dict,
):
    model = XGBSignalModel(**config.get("model_params", {}))
    trainer = XGBSignalTrainer(
        model_instance_name=model_name,
        as_of_date=as_of,
        config=config,
    )
    return await trainer.train(model, features)


@pipeline.task
async def run_inference(model_uri: str, features: pd.DataFrame):
    model = registry.load_model(model_uri)
    return model.predict(features)


@pipeline.task
async def save_signals(signals: pd.Series, output_name: str, as_of: str):
    df = signals.to_frame(name="signal")
    return await write_dataset(df, output_name, knowledge_date=as_of)


@pipeline.flow
async def signal_generation_flow(
    model_name: str,
    feature_dataset: str,
    output_dataset: str,
    as_of: str,
    config: dict,
):
    """End-to-end signal generation pipeline."""

    # Load features
    features = await load_features(feature_dataset, as_of)

    # Train model
    model_uri = await train_signal_model(model_name, features, as_of, config)

    # Run inference
    signals = await run_inference(model_uri, features)

    # Save output
    version_id = await save_signals(signals, output_dataset, as_of)

    return {"model_uri": model_uri, "output_version": version_id}


# Schedule weekly retraining
pipeline.schedule(
    signal_generation_flow,
    cron="0 0 * * SUN",
    name="weekly_signal_training",
)
```
