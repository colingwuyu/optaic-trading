# DTO Patterns

## Standard DTO Structure

```python
# libs/core/domain/<domain>.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID

class SignalCreateDTO(BaseModel):
    """Input for creating a signal."""
    name: str
    signal_type: str
    frequency: str
    lookback_days: Optional[int] = None
    config: Optional[Dict[str, Any]] = None

class SignalUpdateDTO(BaseModel):
    """Input for updating a signal."""
    lookback_days: Optional[int] = None
    config: Optional[Dict[str, Any]] = None

class SignalReadDTO(BaseModel):
    """Output representation of a signal."""
    id: UUID
    resource_id: UUID
    name: str
    signal_type: str
    frequency: str
    lookback_days: Optional[int]
    config: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

## Definition DTO Pattern

```python
class PipelineDefCreateDTO(BaseModel):
    """Submit a new pipeline definition."""
    name: str
    kind: str  # etl, expression, training
    interface_version: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    config_schema: Optional[Dict[str, Any]] = None

class PipelineDefReadDTO(BaseModel):
    """Pipeline definition output."""
    id: UUID
    resource_id: UUID
    kind: str
    interface_version: str
    evaluation_status: str
    input_schema: Optional[Dict[str, Any]]
    output_schema: Optional[Dict[str, Any]]
    config_schema: Optional[Dict[str, Any]]

    model_config = ConfigDict(from_attributes=True)
```

## Instance DTO Pattern

```python
class InstanceRef(BaseModel):
    """Reference to a definition with config."""
    def_id: UUID
    def_version: str
    config: Dict[str, Any]

class DatasetInstanceCreateDTO(BaseModel):
    """Create a dataset instance."""
    name: str
    pipeline: InstanceRef
    store: InstanceRef
    accessor: InstanceRef
    schedule: Optional[Dict[str, Any]] = None

class DatasetInstanceReadDTO(BaseModel):
    """Dataset instance output."""
    id: UUID
    resource_id: UUID
    name: str
    pipeline_def_id: UUID
    pipeline_config: Dict[str, Any]
    store_def_id: UUID
    store_config: Dict[str, Any]
    accessor_def_id: UUID
    accessor_config: Dict[str, Any]
    schedule: Optional[Dict[str, Any]]
    freshness_state: str

    model_config = ConfigDict(from_attributes=True)
```

## Adapter-Friendly DTOs

For orchestration/tracking systems, use generic fields:

```python
class RunDTO(BaseModel):
    """Orchestrator-agnostic run representation."""
    id: UUID
    resource_id: UUID
    status: str

    # Generic adapter fields
    orchestrator_kind: Optional[str] = None  # "prefect", "local"
    orchestrator_run_id: Optional[str] = None
    orchestrator_metadata: Optional[Dict[str, Any]] = None

class ModelVersionDTO(BaseModel):
    """Registry-agnostic model version."""
    id: UUID
    resource_id: UUID
    version: str

    # Generic adapter fields
    registry_kind: Optional[str] = None  # "mlflow", "local"
    registry_model_id: Optional[str] = None
    registry_metadata: Optional[Dict[str, Any]] = None
```
