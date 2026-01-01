# Model Instance Patterns

Model Instances are concrete configurations that reference MLModuleDefs and compose datasets.

## Model Instance Structure

```python
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from datetime import datetime

class MLModuleDefRef(BaseModel):
    """Reference to a specific version of an MLModuleDef."""
    def_id: UUID
    def_version: str  # e.g., "2.1.0"

class DatasetInstanceRef(BaseModel):
    """Reference to a dataset instance."""
    dataset_id: UUID
    # Optional: pin to specific version
    version_id: UUID | None = None

class ScheduleConfig(BaseModel):
    """Cron-based schedule configuration."""
    cron: str  # e.g., "0 18 * * 1-5"
    timezone: str = "UTC"
    enabled: bool = True

class ModelInstanceConfig(BaseModel):
    """Configuration for model training/inference."""
    target_col: str
    feature_cols: list[str] | None = None  # None = use all
    feature_lag: int = Field(1, ge=0, description="Lag features to avoid lookahead")
    train_window: int = Field(252 * 5, description="Training window in days")
    retrain_frequency: str = "weekly"  # daily, weekly, monthly

class ModelInstance(BaseModel):
    """A concrete model instance in MLOps Center."""

    # Identity
    id: UUID
    name: str
    description: str | None = None

    # Definition reference
    model_def: MLModuleDefRef

    # Dataset composition
    training_datasets: list[DatasetInstanceRef]
    inference_datasets: list[DatasetInstanceRef]
    output_dataset: DatasetInstanceRef  # Where predictions are written

    # Configuration
    config: ModelInstanceConfig

    # Scheduling
    schedule: dict[str, ScheduleConfig] = Field(
        default_factory=lambda: {
            "training": ScheduleConfig(cron="0 0 * * 0"),  # Weekly
            "inference": ScheduleConfig(cron="0 18 * * 1-5"),  # Daily
        }
    )

    # Metadata
    owner_id: UUID
    space_id: UUID
    created_at: "datetime"
    updated_at: "datetime"

    # Current state
    active_model_version_id: UUID | None = None
    status: str = "pending"  # pending, training, ready, error
```

## Model Instance Service

```python
# libs/core/domain/model_instance_service.py
from typing import TYPE_CHECKING
from uuid import UUID

from libs.core.activity import record_activity_with_outbox
from libs.core.guardrails import GuardrailsEngine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

class ModelInstanceService:
    """CRUD operations for model instances."""

    async def create(
        self,
        session: "AsyncSession",
        data: "ModelInstanceCreate",
        actor_id: UUID,
    ) -> "ModelInstance":
        """Create a new model instance."""

        # Validate against guardrails
        await GuardrailsEngine.validate_at_gate(
            gate="resource.create",
            resource_type="model_instance",
            data=data.model_dump(),
            session=session,
        )

        # Create in DB
        instance = await self._create_db_record(session, data)

        # Emit activity
        await record_activity_with_outbox(
            session=session,
            actor_id=actor_id,
            resource_id=instance.id,
            action="model_instance.created",
            payload={
                "name": instance.name,
                "model_def_id": str(data.model_def.def_id),
                "model_def_version": data.model_def.def_version,
            },
        )

        return instance

    async def update_active_version(
        self,
        session: "AsyncSession",
        instance_id: UUID,
        model_version_id: UUID,
        actor_id: UUID,
    ) -> "ModelInstance":
        """Update the active model version after training."""

        instance = await self._get_by_id(session, instance_id)
        old_version = instance.active_model_version_id

        instance.active_model_version_id = model_version_id
        instance.status = "ready"

        await record_activity_with_outbox(
            session=session,
            actor_id=actor_id,
            resource_id=instance_id,
            action="model_instance.version_activated",
            payload={
                "old_version_id": str(old_version) if old_version else None,
                "new_version_id": str(model_version_id),
            },
        )

        return instance
```

## Model Instance DTO

```python
# libs/core/domain/model_instance_dto.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class ModelInstanceCreate(BaseModel):
    """DTO for creating a model instance."""
    name: str
    description: str | None = None
    model_def: MLModuleDefRef
    training_datasets: list[DatasetInstanceRef]
    inference_datasets: list[DatasetInstanceRef]
    output_dataset: DatasetInstanceRef
    config: ModelInstanceConfig
    schedule: dict[str, ScheduleConfig] | None = None

class ModelInstanceResponse(BaseModel):
    """DTO for API responses."""
    id: UUID
    name: str
    description: str | None
    model_def_id: UUID
    model_def_version: str
    training_dataset_ids: list[UUID]
    output_dataset_id: UUID
    status: str
    active_model_version_id: UUID | None
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
```

## Example: Creating a Signal Model Instance

```python
from optaic import SDK

sdk = SDK()

# Create model instance for SPX alpha signal
model_instance = await sdk.mlops.create_model_instance(
    name="SPX_Alpha_Signal_Model",
    description="XGBoost signal model for SPX alpha generation",
    model_def="xgb-signal-model",
    model_def_version="2.1.0",
    training_datasets=[
        "SPX_Features_Daily",
        "SPX_Returns_Daily",
    ],
    inference_datasets=[
        "SPX_Features_Daily",
    ],
    output_dataset="SPX_Alpha_Signal",
    config={
        "target_col": "fwd_return_5d",
        "feature_lag": 1,
        "train_window": 252 * 5,  # 5 years
    },
    schedule={
        "training": {"cron": "0 0 * * 0"},     # Sunday midnight
        "inference": {"cron": "0 18 * * 1-5"}, # Weekday 6pm
    }
)

print(f"Created model instance: {model_instance.id}")
```

## Model Categories and Their Instances

### Signal Model Instance
```python
# Generates alpha signals [-1, 1]
ModelInstance(
    name="Momentum_Signal_Model",
    model_def=MLModuleDefRef(def_id="...", def_version="1.0.0"),
    output_dataset=DatasetInstanceRef(dataset_id="momentum_signal"),
    config=ModelInstanceConfig(
        target_col="fwd_return_5d",
        feature_cols=["momentum_20d", "vol_20d", "reversal_5d"],
    ),
)
```

### Macro Regime Model Instance
```python
# Classifies market regimes
ModelInstance(
    name="Market_Regime_Classifier",
    model_def=MLModuleDefRef(def_id="...", def_version="1.0.0"),
    output_dataset=DatasetInstanceRef(dataset_id="regime_labels"),
    config=ModelInstanceConfig(
        target_col="regime_label",
        feature_cols=["vix", "yield_curve", "credit_spread"],
    ),
)
```

### Signal Combining Model Instance
```python
# Combines multiple signals into one
ModelInstance(
    name="Alpha_Combiner",
    model_def=MLModuleDefRef(def_id="...", def_version="1.0.0"),
    training_datasets=[
        DatasetInstanceRef(dataset_id="momentum_signal"),
        DatasetInstanceRef(dataset_id="value_signal"),
        DatasetInstanceRef(dataset_id="quality_signal"),
    ],
    output_dataset=DatasetInstanceRef(dataset_id="combined_alpha"),
    config=ModelInstanceConfig(
        target_col="fwd_return_5d",
    ),
)
```
