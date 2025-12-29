from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """
    Pipeline/flow execution run.

    Adapter-friendly design: uses generic orchestrator_* columns instead of
    vendor-specific fields. The orchestrator_kind indicates which adapter
    (e.g., "prefect", "local", "airflow") manages this run.
    """

    __tablename__ = "runs"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Status and execution tracking
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued"
    )  # queued|running|succeeded|failed|canceled
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_principal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Adapter-friendly orchestrator mapping
    orchestrator_kind: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # e.g., "prefect", "local", "airflow"
    orchestrator_run_id: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )  # external run id
    orchestrator_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # DEPRECATED: kept for backward compatibility, use orchestrator_* instead
    prefect_flow_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_runs_tenant_resource", "tenant_id", "resource_id"),
        Index("ix_runs_status", "status"),
    )


class TrainingRun(Base):
    """
    ML training run execution.

    Adapter-friendly design: uses generic tracking_* columns instead of
    vendor-specific fields. The tracking_kind indicates which adapter
    (e.g., "mlflow", "wandb") tracks this run.
    """

    __tablename__ = "training_runs"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Adapter-friendly tracking mapping
    tracking_kind: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # e.g., "mlflow", "wandb"
    tracking_run_id: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )  # external tracking run id
    tracking_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # DEPRECATED: kept for backward compatibility, use tracking_* instead
    mlflow_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (Index("ix_training_runs_tenant_resource", "tenant_id", "resource_id"),)


class ModelVersion(Base):
    """
    Registered model version in model registry.

    Adapter-friendly design: uses generic registry_* columns instead of
    vendor-specific fields. The registry_kind indicates which adapter
    (e.g., "mlflow", "sagemaker") manages this model.
    """

    __tablename__ = "model_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Adapter-friendly registry mapping
    registry_kind: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # e.g., "mlflow", "sagemaker"
    registry_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registry_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registry_model_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    registry_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # DEPRECATED: kept for backward compatibility, use registry_* instead
    mlflow_registered_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mlflow_registered_model_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    __table_args__ = (Index("ix_model_versions_tenant_resource", "tenant_id", "resource_id"),)

