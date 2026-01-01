# MLModuleDef 5-Component Structure

ML Model Definitions are more complex than other plugin definitions, containing five code components.

## Directory Structure

```
MLModelDef/
├── model/                    # 1. ML Model Source Code
│   ├── __init__.py
│   ├── architecture.py       # Model class/architecture
│   ├── config.py             # Hyperparameter schema (Pydantic)
│   └── base.py               # Base model interface
│
├── training/                 # 2. Training/Evaluation Source Code
│   ├── __init__.py
│   ├── trainer.py            # Training loop, loss, optimizer
│   ├── evaluator.py          # Evaluation metrics, validation
│   ├── config.py             # Training config schema
│   └── callbacks.py          # Training callbacks (logging, checkpoints)
│
├── inference/                # 3. Inference Source Code
│   ├── __init__.py
│   ├── predictor.py          # Single prediction interface
│   ├── batch_inference.py    # Batch prediction for datasets
│   └── config.py             # Inference config schema
│
├── monitoring/               # 4. Data & Performance Monitoring
│   ├── __init__.py
│   ├── data_monitor.py       # Input data drift detection
│   ├── perf_monitor.py       # Model performance tracking
│   └── alerts.py             # Alert rule definitions
│
├── tests/                    # 5. Test Suite
│   ├── __init__.py
│   ├── test_model.py         # Model instantiation, forward pass
│   ├── test_training.py      # Training loop, checkpointing
│   ├── test_inference.py     # Prediction correctness
│   └── test_monitoring.py    # Drift detection, alerting
│
└── docs/                     # Documentation
    ├── README.md             # Overview, usage
    └── API.md                # Interface documentation
```

## Component Interfaces

### 1. Model Component

```python
# model/base.py
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch
    import pandas as pd

class BaseModel(ABC):
    """Abstract base for all ML models."""

    @abstractmethod
    def forward(self, features: "pd.DataFrame") -> "pd.DataFrame":
        """Run forward pass."""
        pass

    @abstractmethod
    def get_config_schema(self) -> type:
        """Return Pydantic config schema."""
        pass
```

```python
# model/architecture.py
from typing import TYPE_CHECKING
from .base import BaseModel
from .config import XGBModelConfig

if TYPE_CHECKING:
    import pandas as pd
    import xgboost as xgb

class XGBSignalModel(BaseModel):
    """XGBoost-based signal model."""

    def __init__(self, config: XGBModelConfig):
        self.config = config
        self._model: "xgb.Booster | None" = None

    def forward(self, features: "pd.DataFrame") -> "pd.DataFrame":
        import pandas as pd
        import xgboost as xgb

        dmatrix = xgb.DMatrix(features)
        preds = self._model.predict(dmatrix)
        return pd.DataFrame({"signal": preds}, index=features.index)

    def get_config_schema(self) -> type:
        return XGBModelConfig
```

```python
# model/config.py
from pydantic import BaseModel, Field

class XGBModelConfig(BaseModel):
    """Hyperparameters for XGBoost signal model."""

    n_estimators: int = Field(100, ge=1)
    max_depth: int = Field(6, ge=1, le=20)
    learning_rate: float = Field(0.1, gt=0, le=1)
    subsample: float = Field(0.8, gt=0, le=1)
    colsample_bytree: float = Field(0.8, gt=0, le=1)
```

### 2. Training Component

```python
# training/trainer.py
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from ..model.base import BaseModel

class BaseTrainer(ABC):
    """Abstract trainer interface."""

    @abstractmethod
    def train(
        self,
        model: "BaseModel",
        train_data: "pd.DataFrame",
        val_data: "pd.DataFrame | None" = None,
    ) -> "TrainingResult":
        pass

    @abstractmethod
    def get_config_schema(self) -> type:
        pass

class TrainingResult:
    """Result of a training run."""
    model_artifact: bytes
    metrics: dict
    hyperparams: dict
    train_duration_sec: float
```

```python
# training/evaluator.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

class ModelEvaluator:
    """Evaluate model on validation/test sets."""

    def evaluate(
        self,
        predictions: "pd.DataFrame",
        actuals: "pd.DataFrame",
    ) -> dict:
        """Return metrics dict."""
        import numpy as np

        # Signal model metrics
        ic = np.corrcoef(predictions["signal"], actuals["target"])[0, 1]
        mse = ((predictions["signal"] - actuals["target"]) ** 2).mean()

        return {
            "ic": ic,
            "mse": mse,
            "signal_mean": predictions["signal"].mean(),
            "signal_std": predictions["signal"].std(),
        }
```

### 3. Inference Component

```python
# inference/predictor.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from ..model.base import BaseModel

class Predictor:
    """Single-row or batch prediction interface."""

    def __init__(self, model: "BaseModel"):
        self.model = model

    def predict(self, features: "pd.DataFrame") -> "pd.DataFrame":
        """Generate predictions."""
        return self.model.forward(features)
```

```python
# inference/batch_inference.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from optaic.sdk import SDK

class BatchInference:
    """Run inference on dataset and write to output dataset."""

    def __init__(self, predictor: "Predictor", sdk: "SDK"):
        self.predictor = predictor
        self.sdk = sdk

    async def run(
        self,
        input_dataset_id: str,
        output_dataset_id: str,
        as_of_date: str,
    ) -> "InferenceResult":
        """Run batch inference pipeline."""
        # Read features via PIT accessor
        features = await self.sdk.data.query(
            dataset_id=input_dataset_id,
            as_of_date=as_of_date,
        )

        # Generate predictions
        predictions = self.predictor.predict(features)

        # Write to output dataset
        await self.sdk.data.write(
            dataset_id=output_dataset_id,
            data=predictions,
            knowledge_date=as_of_date,
        )

        return InferenceResult(
            rows_processed=len(predictions),
            as_of_date=as_of_date,
        )
```

### 4. Monitoring Component

```python
# monitoring/data_monitor.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

class DataMonitor:
    """Monitor input data drift."""

    def __init__(self, baseline_stats: dict):
        self.baseline_stats = baseline_stats

    def check_drift(
        self,
        current_data: "pd.DataFrame",
        threshold: float = 0.1,
    ) -> "DriftReport":
        """Compare current data distribution to baseline."""
        import numpy as np

        drift_scores = {}
        for col in current_data.columns:
            if col in self.baseline_stats:
                baseline_mean = self.baseline_stats[col]["mean"]
                current_mean = current_data[col].mean()
                drift = abs(current_mean - baseline_mean) / (baseline_mean + 1e-8)
                drift_scores[col] = drift

        has_drift = any(v > threshold for v in drift_scores.values())

        return DriftReport(
            drift_scores=drift_scores,
            threshold=threshold,
            has_drift=has_drift,
        )
```

```python
# monitoring/perf_monitor.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

class PerformanceMonitor:
    """Monitor model performance degradation."""

    def __init__(self, baseline_metrics: dict):
        self.baseline_metrics = baseline_metrics

    def check_degradation(
        self,
        predictions: "pd.DataFrame",
        realized: "pd.DataFrame",
    ) -> "PerformanceReport":
        """Compare realized performance to baseline."""
        import numpy as np

        # Calculate realized IC
        realized_ic = np.corrcoef(
            predictions["signal"],
            realized["realized_return"]
        )[0, 1]

        baseline_ic = self.baseline_metrics.get("ic", 0)
        degradation = (baseline_ic - realized_ic) / (abs(baseline_ic) + 1e-8)

        return PerformanceReport(
            realized_metrics={"ic": realized_ic},
            baseline_metrics=self.baseline_metrics,
            degradation_pct=degradation * 100,
            is_degraded=degradation > 0.2,  # 20% threshold
        )
```

### 5. Tests Component

```python
# tests/test_model.py
import pytest

def test_model_instantiation():
    """Test model can be created with valid config."""
    from ..model.architecture import XGBSignalModel
    from ..model.config import XGBModelConfig

    config = XGBModelConfig(n_estimators=10, max_depth=3)
    model = XGBSignalModel(config)

    assert model.config.n_estimators == 10
    assert model.config.max_depth == 3

def test_model_forward_pass():
    """Test model forward pass shape."""
    import pandas as pd
    import numpy as np

    from ..model.architecture import XGBSignalModel
    from ..model.config import XGBModelConfig

    config = XGBModelConfig()
    model = XGBSignalModel(config)

    # Mock trained model
    features = pd.DataFrame(
        np.random.randn(100, 5),
        columns=[f"feature_{i}" for i in range(5)]
    )

    # Would need trained model for real test
    # predictions = model.forward(features)
    # assert predictions.shape == (100, 1)
    # assert "signal" in predictions.columns
```

## Registration

After creating MLModuleDef, register it:

```python
# In libs/core/resources.py
class ResourceType(str, Enum):
    # ... existing types ...
    ML_MODULE_DEF = "ml_module_def"
    MODEL_INSTANCE = "model_instance"
```

## Submission Flow

1. Developer packages MLModuleDef with all 5 components
2. Submit via SDK to personal/staging
3. EvaluationRun executes: pytest (all test_*.py), ruff, interface checks
4. If passed, available for promotion
5. Promote to team/system for shared use
