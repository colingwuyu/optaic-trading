"""
Quant Domain Models

Extension tables for quant trading resources following the Definition → Instance → Run pattern.

Definition Resources (the "Law"):
- PipelineDefinition: Data pipeline plugins (ETL, expression, transform)
- StoreDefinition: Storage backend plugins (Parquet, SQLite, Virtual)
- AccessorDefinition: Data access pattern plugins (Simple, PIT, Field)
- OpDefinition: Mathematical operator definitions (REF, DELTA, MEAN)
- MLModuleDefinition: ML model template definitions
- PortfolioOptimizerDefinition: Portfolio optimization algorithm definitions

Instance Resources (configured usages):
- PipelineInstance: Configured pipeline with schedule
- StoreInstance: Configured storage with physical path
- AccessorInstance: Configured accessor
- DatasetInstance: Composed dataset (Pipeline + Store + Accessor)
- SignalSpec: Signal-specific metadata for promoted datasets
- ExperimentInstance: Expression experiment configuration
- ModelInstance: Configured ML model instance
- PortfolioOptimizerInstance: Configured optimizer with constraints
- BacktestInstance: Backtest configuration (no definition - fixed procedure)

Run Resources (execution records):
- BacktestRun: Backtest execution results
- PortfolioOptimizationRun: Portfolio optimization results
- InferenceRun: Model inference results
- MonitoringRun: Data/model monitoring results

Lineage:
- DatasetLineage: Tracks upstream/downstream dependencies
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import JSONType, UUIDArrayType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# DEFINITION RESOURCES (The Law)
# =============================================================================


class PipelineDefinition(Base):
    """
    Data pipeline plugin definition.

    Contains interface spec, schemas, and guardrail contracts that Instances must follow.
    Categories: etl, expression, transform
    """

    __tablename__ = "pipeline_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Definition metadata
    category: Mapped[str] = mapped_column(String(50))  # etl, expression, transform
    interface_spec: Mapped[str] = mapped_column(
        String(255)
    )  # e.g., optaic.interfaces.BasePipeline
    code_ref: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )  # S3/Git path

    # Schemas (the "Law")
    input_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Compatibility and contracts
    compatibility_rules: Mapped[dict] = mapped_column(JSONType, default=dict)
    guardrail_contracts: Mapped[list] = mapped_column(JSONType, default=list)

    # Evaluation
    test_suite_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    evaluation_status: Mapped[str] = mapped_column(String(32), default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_pipeline_defs_tenant_category", "tenant_id", "category"),
    )


class StoreDefinition(Base):
    """
    Storage backend plugin definition.

    Backends: parquet, sqlite, virtual
    """

    __tablename__ = "store_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    backend_type: Mapped[str] = mapped_column(String(50))  # parquet, sqlite, virtual
    interface_spec: Mapped[str] = mapped_column(String(255))
    code_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    guardrail_contracts: Mapped[list] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_store_defs_tenant_backend", "tenant_id", "backend_type"),
    )


class AccessorDefinition(Base):
    """
    Data accessor plugin definition.

    Accessor types: simple, pit (point-in-time), field
    """

    __tablename__ = "accessor_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    accessor_type: Mapped[str] = mapped_column(String(50))  # simple, pit, field
    interface_spec: Mapped[str] = mapped_column(String(255))
    code_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    guardrail_contracts: Mapped[list] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_accessor_defs_tenant_type", "tenant_id", "accessor_type"),
    )


class OpDefinition(Base):
    """
    Mathematical operator definition.

    Categories: rolling, cross_sectional, time_series, statistical
    Examples: REF, DELTA, MEAN, CORR, RANK, ZSCORE
    """

    __tablename__ = "op_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    category: Mapped[str] = mapped_column(String(50))  # rolling, cross_sectional, etc.
    signature: Mapped[str] = mapped_column(
        String(512)
    )  # e.g., MEAN(x: Series, window: int) -> Series
    interface_spec: Mapped[str] = mapped_column(String(255))
    code_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    input_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (Index("ix_op_defs_tenant_category", "tenant_id", "category"),)


class OpMacroDefinition(Base):
    """
    Saved expression/macro definition.

    User-defined formulas that can be reused.
    """

    __tablename__ = "op_macro_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    expression_text: Mapped[str] = mapped_column(Text)
    input_aliases: Mapped[list] = mapped_column(
        JSONType, default=list
    )  # ["price", "volume"]
    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MLModuleDefinition(Base):
    """
    ML model template definition.

    Module types: regressor, classifier, forecaster, ranker
    """

    __tablename__ = "ml_module_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    module_type: Mapped[str] = mapped_column(
        String(50)
    )  # regressor, classifier, forecaster
    interface_spec: Mapped[str] = mapped_column(String(255))
    code_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    input_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)

    guardrail_contracts: Mapped[list] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_ml_module_defs_tenant_type", "tenant_id", "module_type"),
    )


class PortfolioOptimizerDefinition(Base):
    """
    Portfolio optimization algorithm definition.

    Algorithm types: mvo (mean-variance), hrp (hierarchical risk parity),
    black_litterman, risk_parity, rl (reinforcement learning)
    """

    __tablename__ = "portfolio_optimizer_definitions"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    algorithm_type: Mapped[str] = mapped_column(
        String(50)
    )  # mvo, hrp, black_litterman, etc.
    interface_spec: Mapped[str] = mapped_column(String(255))
    code_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    input_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSONType, default=dict)
    parameters_schema: Mapped[dict] = mapped_column(JSONType, default=dict)

    guardrail_contracts: Mapped[list] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_portfolio_opt_defs_tenant_algo", "tenant_id", "algorithm_type"),
    )


# =============================================================================
# INSTANCE RESOURCES (Configured Usages)
# =============================================================================


class PipelineInstance(Base):
    """
    Configured pipeline instance with schedule.
    """

    __tablename__ = "pipeline_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Definition reference
    definition_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    definition_version_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resource_versions.id"), nullable=True
    )

    # Configuration
    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    schedule_json: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_pipeline_inst_tenant_def", "tenant_id", "definition_resource_id"),
    )


class StoreInstance(Base):
    """
    Configured storage instance with physical path.
    """

    __tablename__ = "store_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    definition_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))

    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    physical_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class AccessorInstance(Base):
    """
    Configured accessor instance.
    """

    __tablename__ = "accessor_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    definition_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))

    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class DatasetInstance(Base):
    """
    Composed dataset instance.

    Composes Pipeline + Store + Accessor into a unified data asset.

    External system registration:
    - prefect_deployment_id: Prefect Deployment for scheduled/triggered runs
    - When Instance is created, a Prefect Deployment is registered
    - Each PipelineRun creates a Prefect Flow Run under this deployment
    """

    __tablename__ = "dataset_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Composition references
    pipeline_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    store_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    accessor_instance_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))

    # External system registration (Instance = Registration Point)
    prefect_deployment_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Prefect Deployment ID for scheduled runs

    # Lineage: cached upstream dependencies (computed at creation time)
    # This enables quick dependency checks without querying dataset_lineage table
    upstream_resource_ids: Mapped[Optional[list[str]]] = mapped_column(
        UUIDArrayType, nullable=True, default=list
    )  # List of upstream DatasetInstance IDs

    # Upstream status tracking (for pub/sub pattern)
    # Key: upstream_resource_id (str), Value: "ready" | "stale" | "running" | "error"
    upstream_status: Mapped[Optional[dict]] = mapped_column(
        JSONType, nullable=True, default=dict
    )  # Tracks status of each upstream dependency

    # Freshness tracking
    freshness_status: Mapped[str] = mapped_column(
        String(32), default="unknown"
    )  # fresh, stale, unknown
    last_data_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Execution configuration
    auto_trigger: Mapped[bool] = mapped_column(default=False, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_dataset_inst_tenant_freshness", "tenant_id", "freshness_status"),
    )


class DatasetStatus(Base):
    """
    Execution status tracking for dataset instances.

    Stores pipeline execution metadata for freshness tracking and
    orchestration decisions. Used by StatusStore.
    """

    __tablename__ = "dataset_status"

    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Pipeline execution tracking
    last_pipeline_run: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_pipeline_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # running, success, error, empty

    # Data freshness
    last_data_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    rows_processed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Source monitoring
    last_source_check: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_delay_detected: Mapped[bool] = mapped_column(
        default=False, server_default=text("0")
    )

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_dataset_status_tenant_status", "tenant_id", "last_pipeline_status"),
    )


class SignalSpec(Base):
    """
    Signal specification for promoted datasets.

    Contains signal-specific metadata like bounds, neutral value, index schema.
    """

    __tablename__ = "signal_specs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Signal bounds
    min_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=-1.0
    )
    max_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=1.0
    )
    allow_nan: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    neutral_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0
    )

    # Index schema (columns, frequency)
    index_schema_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Source expression (if derived)
    source_expression: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_dataset_ids: Mapped[Optional[list]] = mapped_column(
        UUIDArrayType, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ExperimentInstance(Base):
    """
    Expression experiment configuration.
    """

    __tablename__ = "experiment_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    expression_text: Mapped[str] = mapped_column(Text)
    input_datasets_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # alias -> dataset_id
    preview_config_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ModelInstance(Base):
    """
    Configured ML model instance.

    External system registration:
    - mlflow_experiment_id: MLflow Experiment for all training runs
    - mlflow_registered_model_name: MLflow Model Registry name (after promotion)
    - evidently_project_id: EvidentlyAI Project for monitoring

    Lifecycle:
    1. Instance created → MLflow Experiment registered
    2. TrainingRun created → MLflow Run under the Experiment
    3. Model promoted → Registered in MLflow Model Registry
    4. Monitoring enabled → Evidently Project created
    5. MonitoringRun → Evidently Report under the Project
    """

    __tablename__ = "model_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    definition_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    definition_version_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resource_versions.id"), nullable=True
    )

    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # External system registration (Instance = Registration Point)
    mlflow_experiment_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # MLflow Experiment ID for training runs
    mlflow_registered_model_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # MLflow Model Registry name (after promotion)
    evidently_project_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # EvidentlyAI Project ID for monitoring

    # Training dataset reference
    training_dataset_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )
    last_trained_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_model_inst_tenant_def", "tenant_id", "definition_resource_id"),
    )


class PortfolioOptimizerInstance(Base):
    """
    Configured portfolio optimizer instance with constraints.
    """

    __tablename__ = "portfolio_optimizer_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    definition_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))

    config_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    constraints_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Input references
    input_signal_ids: Mapped[Optional[list]] = mapped_column(
        UUIDArrayType, nullable=True
    )
    covariance_dataset_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index(
            "ix_portfolio_opt_inst_tenant_def", "tenant_id", "definition_resource_id"
        ),
    )


class BacktestInstance(Base):
    """
    Backtest configuration.

    Note: No definition reference - backtest procedure is fixed.
    """

    __tablename__ = "backtest_instances"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Asset configuration
    assets_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # universe, benchmark

    # Signal configuration
    signals_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # primary, secondary, optimizer

    # Date range
    date_range_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # start, end, frequency

    # Execution configuration
    config_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # rebalance, costs, slippage

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


# =============================================================================
# RUN RESOURCES (Execution Records)
# =============================================================================


class PipelineRun(Base):
    """
    Pipeline execution run for dataset refresh.

    Tracks execution of a DatasetInstance's pipeline, including:
    - Mode: "overwrite" (full history) or "incremental" (append)
    - Results: rows processed, date range, timing
    - Lineage: which versions of upstream datasets were used
    """

    __tablename__ = "pipeline_runs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Parent reference (DatasetInstance)
    dataset_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )

    # Execution mode
    mode: Mapped[str] = mapped_column(
        String(32), default="overwrite"
    )  # overwrite/incremental

    # Orchestrator tracking
    orchestrator_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    orchestrator_run_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    orchestrator_meta_json: Mapped[Optional[dict]] = mapped_column(
        JSONType, nullable=True
    )

    # Results
    rows_processed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    start_data_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_data_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Timing (in milliseconds)
    extract_duration_ms: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    transform_duration_ms: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    load_duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(32), default="queued"
    )  # queued/running/completed/failed/cancelled
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lineage (versions of upstream datasets used)
    input_versions_json: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_pipeline_runs_tenant_dataset", "tenant_id", "dataset_instance_id"),
        Index("ix_pipeline_runs_status", "status"),
    )


class ExperimentRun(Base):
    """
    Expression evaluation run (preview API).

    Tracks execution of an ExperimentInstance's expression, including:
    - Expression evaluated
    - Input datasets used (with versions)
    - Output data reference or preview
    """

    __tablename__ = "experiment_runs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Parent reference (ExperimentInstance)
    experiment_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )

    # Expression executed
    expression_text: Mapped[str] = mapped_column(Text)

    # Input datasets used (with versions)
    input_versions_json: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    # Date range evaluated
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # PIT

    # Orchestrator tracking
    orchestrator_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    orchestrator_run_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Status
    status: Mapped[str] = mapped_column(String(32), default="queued")

    # Results
    result_columns: Mapped[Optional[list]] = mapped_column(JSONType, nullable=True)
    row_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    result_preview_json: Mapped[Optional[dict]] = mapped_column(
        JSONType, nullable=True
    )  # First N rows for preview

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index(
            "ix_experiment_runs_tenant_experiment",
            "tenant_id",
            "experiment_instance_id",
        ),
    )


class BacktestRun(Base):
    """
    Backtest execution results.
    """

    __tablename__ = "backtest_runs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    backtest_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )

    # Metrics
    metrics_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # sharpe, drawdown, etc.
    trades_json: Mapped[list] = mapped_column(
        JSONType, default=list
    )  # For small trade lists

    # Artifact references (for large outputs)
    equity_curve_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    trades_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    weights_history_ref: Mapped[Optional[str]] = mapped_column(
        String(1024), nullable=True
    )

    # Lineage
    input_versions_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_backtest_runs_tenant_instance", "tenant_id", "backtest_instance_id"),
    )


class PortfolioOptimizationRun(Base):
    """
    Portfolio optimization execution results.
    """

    __tablename__ = "portfolio_optimization_runs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    optimizer_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )

    # Results
    weights_json: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # asset -> weight
    optimization_metrics_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Solver info
    solver_status: Mapped[str] = mapped_column(String(32), default="unknown")
    iterations: Mapped[Optional[int]] = mapped_column(nullable=True)

    # Constraint satisfaction
    constraints_satisfied: Mapped[bool] = mapped_column(
        default=True, server_default=text("1")
    )
    active_constraints: Mapped[list] = mapped_column(JSONType, default=list)

    # Lineage
    input_versions_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index(
            "ix_portfolio_opt_runs_tenant_instance",
            "tenant_id",
            "optimizer_instance_id",
        ),
    )


class InferenceRun(Base):
    """
    Model inference execution results.
    """

    __tablename__ = "inference_runs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    model_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )

    # Results
    metrics_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    predictions_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Inference config
    inference_params_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Lineage
    input_versions_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    model_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_inference_runs_tenant_model", "tenant_id", "model_instance_id"),
    )


class MonitoringRun(Base):
    """
    Data and model monitoring execution results.

    Monitoring types: model_drift, data_quality, performance
    """

    __tablename__ = "monitoring_runs"

    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    parent_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )
    monitoring_type: Mapped[str] = mapped_column(
        String(50)
    )  # model_drift, data_quality, performance

    # Results
    metrics_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    alerts_json: Mapped[list] = mapped_column(JSONType, default=list)

    # Report
    report_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_monitoring_runs_tenant_parent", "tenant_id", "parent_instance_id"),
        Index("ix_monitoring_runs_type", "monitoring_type"),
    )


# =============================================================================
# LINEAGE
# =============================================================================


class DatasetLineage(Base):
    """
    Tracks upstream/downstream dependencies between resources.

    Edge kinds: depends_on, derived_from, composed_of
    """

    __tablename__ = "dataset_lineage"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    upstream_resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )
    downstream_resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )
    edge_kind: Mapped[str] = mapped_column(
        String(50)
    )  # depends_on, derived_from, composed_of

    # Version tracking
    upstream_version_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resource_versions.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_lineage_tenant_upstream", "tenant_id", "upstream_resource_id"),
        Index("ix_lineage_tenant_downstream", "tenant_id", "downstream_resource_id"),
    )
