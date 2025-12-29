"""
Service-layer DTOs for runs, training runs, model versions, and system engines.

These DTOs are adapter-friendly and do not contain vendor-specific fields.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunDTO(BaseModel):
    """DTO for pipeline/flow execution run."""

    model_config = ConfigDict(from_attributes=True)

    resource_id: UUID
    tenant_id: UUID
    created_at: datetime

    # Status and execution
    status: str = "queued"  # queued|running|succeeded|failed|canceled
    status_updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: str | None = None
    requested_by_principal_id: str | None = None

    # Adapter-friendly orchestrator mapping
    orchestrator_kind: str | None = None  # e.g., "prefect", "local", "airflow"
    orchestrator_run_id: str | None = None
    orchestrator_meta: dict[str, Any] | None = None


class TrainingRunDTO(BaseModel):
    """DTO for ML training run execution."""

    model_config = ConfigDict(from_attributes=True)

    resource_id: UUID
    tenant_id: UUID
    created_at: datetime

    # Adapter-friendly tracking mapping
    tracking_kind: str | None = None  # e.g., "mlflow", "wandb"
    tracking_run_id: str | None = None
    tracking_meta: dict[str, Any] | None = None


class ModelVersionDTO(BaseModel):
    """DTO for registered model version in model registry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    resource_id: UUID
    created_at: datetime

    # Adapter-friendly registry mapping
    registry_kind: str | None = None  # e.g., "mlflow", "sagemaker"
    registry_model_name: str | None = None
    registry_model_version: str | None = None
    registry_model_uri: str | None = None
    registry_meta: dict[str, Any] | None = None


class SystemEngineDTO(BaseModel):
    """DTO for system engine ops observability."""

    model_config = ConfigDict(from_attributes=True)

    id: str  # e.g., "prefect", "mlflow"
    mode: str = "disabled"  # local|remote|disabled
    base_url: str | None = None
    data_dir: str | None = None
    db_uri: str | None = None
    package_version: str | None = None
    last_migrated_at: datetime | None = None
    last_backup_at: datetime | None = None
    health: str | None = None
    health_checked_at: datetime | None = None
