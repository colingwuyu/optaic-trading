from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from libs.core.events import ActivityEventV1


class HealthCheck(BaseModel):
    ok: bool = True


class TenantCreate(BaseModel):
    name: str = Field(examples=["Acme Corp"])


class TenantOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    root_resource_id: Optional[UUID] = None


class PrincipalCreate(BaseModel):
    id: Optional[UUID] = Field(
        default=None, examples=["11111111-1111-1111-1111-111111111111"]
    )
    kind: str = Field(default="user", examples=["user"])
    status: str = Field(default="active", examples=["active"])
    display_name: str = Field(examples=["Dev User"])
    email: Optional[str] = Field(default=None, examples=["dev@example.com"])


class PrincipalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    kind: str
    status: str
    display_name: str
    email: Optional[str]
    created_at: datetime


class ResourceCreate(BaseModel):
    type: str = Field(examples=["Project"])
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    name: str = Field(examples=["Roadmap"])
    metadata: Dict[str, Any] = Field(
        default_factory=dict, examples=[{"break_inheritance": False}]
    )


class ResourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, examples=["Updated name"])
    status: Optional[str] = Field(default=None, examples=["archived"])
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, examples=[{"break_inheritance": True}]
    )


class ResourceMove(BaseModel):
    new_parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: UUID
    type: str
    parent_id: Optional[UUID] = None
    owner_principal_id: UUID
    name: str
    status: str
    metadata: Dict[str, Any] = Field(alias="metadata_json")
    created_at: datetime
    updated_at: datetime


class ResourcePage(BaseModel):
    items: List[ResourceOut]
    next_cursor: Optional[str] = None


class ResourceTree(BaseModel):
    resource: ResourceOut
    children: List["ResourceTree"] = Field(default_factory=list)


class RoleBindingCreate(BaseModel):
    principal_id: UUID
    role_name: str = Field(examples=["viewer"])
    scope_resource_id: UUID


class RoleBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    scope_resource_id: UUID
    role_name: str
    granted_by: UUID
    granted_at: datetime
    revoked_at: Optional[datetime] = None


class EffectivePermissionsOut(BaseModel):
    principal_id: UUID
    resource_id: UUID
    permissions: List[str]


class ActivityPage(BaseModel):
    items: List[ActivityEventV1]
    next_cursor: Optional[str] = None


class BranchCreate(BaseModel):
    ref_name: str = Field(examples=["feature-x"])
    from_ref: str = Field(default="main", examples=["main"])


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_id: UUID
    ref_name: str
    head_version_id: UUID
    updated_by: UUID
    updated_at: datetime


class MergeRequestCreate(BaseModel):
    target_resource_id: UUID
    source_ref: str = Field(examples=["feature-x"])
    target_ref: str = Field(default="main", examples=["main"])
    title: Optional[str] = Field(default=None, examples=["Add metric"])
    description: Optional[str] = Field(default=None, examples=["Implements new KPI"])
    required_approvals: int = Field(default=1, ge=0, examples=[1])


class MergeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    mr_resource_id: UUID
    target_resource_id: UUID
    source_ref: str
    target_ref: str
    status: str
    required_approvals: int
    title: Optional[str]
    description: Optional[str]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class MergeApprovalIn(BaseModel):
    decision: str = Field(examples=["approve"])
    comment: Optional[str] = Field(default=None, examples=["Looks good"])


class MergeApprovalOut(BaseModel):
    mr_id: UUID
    decision: str
    approvals: int
    rejects: int
    required_approvals: int
    status: str


class MergeExecuteOut(BaseModel):
    mr_id: UUID
    target_resource_id: UUID
    target_ref: str
    new_version_id: UUID
    status: str


class SubscriptionCreate(BaseModel):
    resource_id: UUID
    scope: str = Field(default="resource", examples=["resource"])


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    resource_id: UUID
    scope: str
    created_at: datetime
    revoked_at: Optional[datetime] = None


class PromotionCreate(BaseModel):
    moving_resource_id: UUID
    to_scope_id: UUID
    placement: Dict[str, Any] = Field(
        default_factory=dict, examples=[{"target": "destination"}]
    )
    mode: str = Field(examples=["move"])
    rbac_template_ref: Optional[str] = Field(default=None, examples=["default"])


class PromotionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: UUID
    pr_resource_id: UUID
    moving_resource_id: UUID
    from_scope_id: Optional[UUID] = None
    to_scope_id: UUID
    placement: Dict[str, Any] = Field(alias="placement_json")
    rbac_template_ref: Optional[str]
    mode: str
    status: str
    required_approvals: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class PromotionApprovalIn(BaseModel):
    decision: str = Field(examples=["approve"])
    comment: Optional[str] = Field(default=None, examples=["Looks good"])


class PromotionApprovalOut(BaseModel):
    pr_id: UUID
    decision: str
    approvals: int
    rejects: int
    required_approvals: int
    status: str


class PromotionExecuteOut(BaseModel):
    pr_id: UUID
    status: str
    mode: str
    new_root_id: Optional[UUID]
    moved_count: int
    copied_count: int


class RealtimeTokenRequest(BaseModel):
    channels: List[str] = Field(
        default_factory=list,
        examples=[
            [
                "t:11111111-1111-1111-1111-111111111111:u:22222222-2222-2222-2222-222222222222",
                "t:11111111-1111-1111-1111-111111111111:r:33333333-3333-3333-3333-333333333333",
                "t:11111111-1111-1111-1111-111111111111:c:44444444-4444-4444-4444-444444444444",
            ]
        ],
    )


class RealtimeTokenResponse(BaseModel):
    connection_token: str
    subscriptions: Dict[str, str] = Field(default_factory=dict)


class RealtimeBootstrapChannel(BaseModel):
    id: UUID
    name: str
    channel: str


class RealtimeBootstrapResource(BaseModel):
    resource_id: UUID
    channel: str


class RealtimeBootstrapResponse(BaseModel):
    tenant_id: UUID
    principal_id: UUID
    inbox_channel: str
    chat_channels: List[RealtimeBootstrapChannel] = Field(default_factory=list)
    resource_subscriptions: List[RealtimeBootstrapResource] = Field(
        default_factory=list
    )
    connection_token: str
    subscription_tokens: Dict[str, str] = Field(default_factory=dict)


class SystemUpgradePlanIn(BaseModel):
    with_redis: bool = False
    check_package_updates: bool = False


class SystemUpgradeStartIn(BaseModel):
    with_redis: bool = False
    apply_package_update: bool = True
    restart: bool = True


class SystemPackageUpdate(BaseModel):
    package: str
    current_version: str
    latest_version: str
    has_update: bool
    source: str
    index_url: Optional[str] = None
    checked_at: str
    message: Optional[str] = None


class SystemInfraAction(BaseModel):
    tool: str
    version: str
    asset_url: str
    asset_sha256: str


class SystemUpgradePlan(BaseModel):
    package_update: Optional[SystemPackageUpdate] = None
    infra_plan: List[SystemInfraAction] = Field(default_factory=list)
    db_migration_needed: bool
    warnings: List[str] = Field(default_factory=list)


class SystemUpgradeStart(BaseModel):
    status: str
    will_restart: bool
    job_path: Optional[str] = None
    message: Optional[str] = None


class SystemRuntimeStatus(BaseModel):
    ok: bool = True
    version: str
    channel: Optional[str] = None
    package_index_url: Optional[str] = None
    db_dialect: Optional[str] = None
    db_alembic_head: Optional[str] = None
    tools: Dict[str, Any] = Field(default_factory=dict)
    centrifugo_engine: str
    with_redis: bool
    last_upgrade_at: Optional[str] = None
    upgrade_status: Dict[str, Any] = Field(default_factory=dict)


class PrefectConfigOut(BaseModel):
    enabled: bool
    bind_host: str
    port: int
    api_url: str
    home_dir: str
    work_pool: str
    worker_limit: int


class MlflowConfigOut(BaseModel):
    enabled: bool
    bind_host: str
    port: int
    tracking_uri: str
    backend_store_uri: str
    artifacts_mode: Literal["direct", "proxied"]
    default_artifact_root: str


class SystemConfig(BaseModel):
    data_dir: str
    prefect: PrefectConfigOut
    mlflow: MlflowConfigOut


class SystemChannelUpdate(BaseModel):
    channel: Literal["prod", "uat", "staging"]


class SystemChannelStatus(BaseModel):
    channel: str
    package_index_url: Optional[str] = None


class ChannelCreate(BaseModel):
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    channel_kind: str = Field(examples=["group"])
    name: str = Field(examples=["Product Updates"])
    topic: Optional[str] = Field(default=None, examples=["Roadmap discussion"])
    settings: Dict[str, Any] = Field(default_factory=dict)


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    channel_kind: str
    topic: Optional[str] = None
    settings: Dict[str, Any]
    created_at: datetime


class MessageCreate(BaseModel):
    body: str = Field(examples=["Hello world"])
    body_json: Optional[Dict[str, Any]] = None


class MessageUpdate(BaseModel):
    body: str = Field(examples=["Updated message"])
    body_json: Optional[Dict[str, Any]] = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    channel_id: UUID
    sender_principal_id: UUID
    body: Optional[str]
    body_json: Optional[Dict[str, Any]]
    status: str
    edited_at: Optional[datetime]
    created_at: datetime


class MessagePage(BaseModel):
    items: List[MessageOut]
    next_cursor: Optional[str] = None


class ReadReceiptIn(BaseModel):
    last_read_message_id: UUID


class ReadReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    channel_id: UUID
    principal_id: UUID
    last_read_message_id: Optional[UUID]
    updated_at: datetime


class AttachmentUploadInitIn(BaseModel):
    channel_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    filename: str = Field(examples=["design.png"])
    content_type: str = Field(examples=["image/png"])
    bytes: int = Field(examples=[1048576])
    checksum: Optional[str] = Field(default=None, examples=["sha256:deadbeef"])


class AttachmentUploadInitOut(BaseModel):
    presigned_put_url: str
    upload_url: Optional[str] = None
    object_key: str
    headers: Dict[str, str] = Field(default_factory=dict)
    expires_in: int = Field(examples=[900])


class AttachmentFinalizeIn(BaseModel):
    message_id: UUID
    object_key: str
    checksum: Optional[str] = Field(default=None, examples=["md5:deadbeef"])


class AttachmentFinalizeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    message_id: UUID
    object_key: str
    filename: str
    content_type: str
    bytes: int
    checksum: str
    created_at: datetime


ResourceTree.model_rebuild()

# ============================================================================
# Quant Domain Schemas
# ============================================================================

# --- Pipeline Schemas ---


class PipelineDefinitionCreate(BaseModel):
    """Create a pipeline definition."""

    name: str = Field(examples=["FRED Pipeline"])
    code_ref: str = Field(examples=["FREDPipeline"])
    category: str = Field(examples=["etl"])
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    interface_spec: str = Field(default="libs.data.pipelines.base.BasePipeline")
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    guardrail_contracts: List[Dict[str, Any]] = Field(default_factory=list)


class PipelineDefinitionOut(BaseModel):
    """Pipeline definition response."""

    id: UUID
    name: str
    code_ref: str
    category: str
    status: str


class PipelineInstanceCreate(BaseModel):
    """Create a pipeline instance from a definition."""

    name: str = Field(examples=["Daily FRED Update"])
    definition_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    config: Dict[str, Any] = Field(default_factory=dict)
    schedule: Dict[str, Any] = Field(default_factory=dict)


class PipelineInstanceOut(BaseModel):
    """Pipeline instance response."""

    id: UUID
    name: str
    definition_id: UUID
    code_ref: str
    status: str


class PipelineRunOut(BaseModel):
    """Pipeline run response."""

    instance_id: UUID
    code_ref: str
    status: str
    message: str


# --- Dataset Schemas ---


class DatasetPreviewRequest(BaseModel):
    """Request dataset preview."""

    start_date: Optional[str] = Field(default=None, examples=["2024-01-01"])
    end_date: Optional[str] = Field(default=None, examples=["2024-12-31"])
    as_of_date: Optional[str] = Field(default=None, examples=["2024-06-15"])
    limit: int = Field(default=100, ge=1, le=1000)


class DatasetPreviewOut(BaseModel):
    """Dataset preview response."""

    id: UUID
    name: str
    columns: List[str]
    data: List[Dict[str, Any]]
    row_count: int
    truncated: bool


class DatasetRefreshOut(BaseModel):
    """Dataset refresh response."""

    id: UUID
    name: str
    status: str
    message: str


class DatasetCreate(BaseModel):
    """Create dataset request."""

    name: str = Field(examples=["SPX OHLCV"])
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    pipeline_instance_id: UUID = Field(
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"]
    )
    store_instance_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    accessor_instance_id: UUID = Field(
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"]
    )
    freshness_status: str = Field(default="unknown", examples=["unknown", "fresh"])


class DatasetOut(BaseModel):
    """Dataset response."""

    id: UUID
    name: str
    type: str = "DatasetInstance"
    status: str = "active"
    freshness_status: str
    pipeline_instance_id: UUID
    store_instance_id: UUID
    accessor_instance_id: UUID


class DatasetStatusOut(BaseModel):
    """Dataset status response."""

    id: UUID
    name: str
    freshness_status: str
    last_data_date: Optional[str] = None
    row_count: Optional[int] = None


# --- Lineage Schemas ---


class LineageNodeOut(BaseModel):
    """Node in a lineage DAG."""

    id: str
    name: str
    type: str  # DatasetInstance, ExperimentInstance, etc.
    status: Optional[str] = None  # ready, stale, running, error, unknown
    direction: str  # upstream, downstream, center


class LineageEdgeOut(BaseModel):
    """Edge in a lineage DAG."""

    source: str  # upstream resource ID
    target: str  # downstream resource ID
    kind: str = "data_dependency"  # data_dependency, schema_dependency, etc.


class LineageFreshnessOut(BaseModel):
    """Freshness status for lineage check."""

    all_ready: bool
    blockers: List[Dict[str, Any]] = Field(default_factory=list)


class LineageDAGOut(BaseModel):
    """Lineage DAG response for visualization.

    This response is designed to be directly usable by
    graph visualization libraries like D3.js, Dagre, or Cytoscape.
    """

    nodes: List[LineageNodeOut]
    edges: List[LineageEdgeOut]
    center_id: str
    execution_order: List[List[str]] = Field(
        default_factory=list,
        description="Batches of resource IDs in topological order",
    )
    freshness: Optional[LineageFreshnessOut] = None


# --- Signal Schemas ---


class SignalRegisterRequest(BaseModel):
    """Register a dataset as a signal."""

    dataset_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    name: str = Field(examples=["momentum_signal"])
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    min_value: float = Field(default=-1.0)
    max_value: float = Field(default=1.0)
    allow_nan: bool = Field(default=False)
    neutral_value: float = Field(default=0.0)


class SignalOut(BaseModel):
    """Signal response."""

    id: UUID
    name: str
    min_value: float
    max_value: float
    allow_nan: bool
    neutral_value: float
    status: str


class SignalValidateOut(BaseModel):
    """Signal validation response."""

    id: UUID
    valid: bool
    issues: List[Dict[str, Any]]


# --- Operator Schemas ---


class OperatorOut(BaseModel):
    """Operator info response."""

    name: str
    category: str
    arity: int
    description: str


class OperatorListOut(BaseModel):
    """List of operators response."""

    operators: List[OperatorOut]
    count: int


class ExpressionEvaluateRequest(BaseModel):
    """Evaluate an expression."""

    expression: str = Field(examples=["MEAN($close, 20)"])
    context: Dict[str, UUID] = Field(
        default_factory=dict,
        examples=[{"close": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"}],
    )
    start_date: Optional[str] = Field(default=None, examples=["2024-01-01"])
    end_date: Optional[str] = Field(default=None, examples=["2024-12-31"])


class ExpressionEvaluateOut(BaseModel):
    """Expression evaluation response."""

    success: bool
    expression: str
    result_type: Optional[str] = None
    columns: Optional[List[str]] = None
    data: Optional[List[Dict[str, Any]]] = None
    value: Optional[Any] = None
    row_count: Optional[int] = None
    truncated: Optional[bool] = None
    errors: Optional[List[str]] = None


# --- Experiment Schemas ---


class ExperimentCreate(BaseModel):
    """Create an experiment."""

    name: str = Field(examples=["Momentum Strategy"])
    expression: str = Field(examples=["CORR($returns, REF($volume, 1), 20)"])
    parent_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    input_datasets: Dict[str, UUID] = Field(default_factory=dict)
    description: Optional[str] = Field(default=None)


class ExperimentOut(BaseModel):
    """Experiment response."""

    id: UUID
    name: str
    expression: str
    operators_used: List[str] = Field(default_factory=list)
    datasets_referenced: List[str] = Field(default_factory=list)
    status: str


class ExperimentRunRequest(BaseModel):
    """Run an experiment."""

    start_date: Optional[str] = Field(default=None, examples=["2024-01-01"])
    end_date: Optional[str] = Field(default=None, examples=["2024-12-31"])
    limit: int = Field(default=100, ge=1, le=1000)


class ExperimentRunOut(BaseModel):
    """Experiment run response."""

    id: Optional[UUID] = None
    success: bool
    name: Optional[str] = None
    expression: Optional[str] = None
    result_type: Optional[str] = None
    columns: Optional[List[str]] = None
    data: Optional[List[Dict[str, Any]]] = None
    value: Optional[Any] = None
    row_count: Optional[int] = None
    truncated: Optional[bool] = None
    error: Optional[str] = None


class ExperimentUpdate(BaseModel):
    """Update an experiment."""

    expression: Optional[str] = Field(default=None)
    input_datasets: Optional[Dict[str, UUID]] = Field(default=None)


class MacroSaveOut(BaseModel):
    """Macro save response."""

    id: UUID
    name: str
    expression: str
    input_aliases: List[str]
    status: str


# --- Run Resource Schemas ---


class PipelineRunSubmitRequest(BaseModel):
    """Submit a pipeline run request."""

    dataset_id: UUID = Field(
        description="DatasetInstance to refresh",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    mode: str = Field(
        default="incremental",
        examples=["incremental", "overwrite"],
        description="Execution mode - incremental or overwrite",
    )
    force: bool = Field(
        default=False,
        description="Force run even if upstreams are stale/error",
    )


class PipelineRunSubmitOut(BaseModel):
    """Pipeline run submission response."""

    id: UUID
    dataset_id: UUID
    orchestrator_run_id: Optional[str] = None
    orchestrator_kind: Optional[str] = None
    mode: str
    status: str
    started_at: Optional[str] = None
    upstream_warning: Optional[str] = None


class PipelineRunStatusOut(BaseModel):
    """Pipeline run status response."""

    id: UUID
    type: str = "PipelineRun"
    name: Optional[str] = None
    dataset_id: UUID
    mode: str
    status: str
    orchestrator_kind: Optional[str] = None
    orchestrator_run_id: Optional[str] = None
    rows_processed: Optional[int] = None
    start_data_date: Optional[str] = None
    end_data_date: Optional[str] = None
    error_summary: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: str


class ExperimentRunSubmitRequest(BaseModel):
    """Submit an experiment preview request."""

    experiment_id: UUID = Field(
        description="ExperimentInstance to run",
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
    )
    start_date: Optional[str] = Field(
        default=None,
        examples=["2024-01-01"],
        description="Start date filter",
    )
    end_date: Optional[str] = Field(
        default=None,
        examples=["2024-12-31"],
        description="End date filter",
    )
    as_of_date: Optional[str] = Field(
        default=None,
        examples=["2024-06-15"],
        description="Point-in-time date for PIT filtering",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum rows to return in preview",
    )


class ExperimentRunSubmitOut(BaseModel):
    """Experiment run submission response."""

    id: UUID
    experiment_id: UUID
    expression: str
    orchestrator_run_id: Optional[str] = None
    orchestrator_kind: Optional[str] = None
    status: str
    started_at: Optional[str] = None


class ExperimentRunStatusOut(BaseModel):
    """Experiment run status response."""

    id: UUID
    type: str = "ExperimentRun"
    name: Optional[str] = None
    experiment_id: UUID
    expression: str
    status: str
    orchestrator_kind: Optional[str] = None
    orchestrator_run_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    as_of_date: Optional[str] = None
    row_count: Optional[int] = None
    result_columns: Optional[List[str]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: str


class ExperimentRunResultsOut(BaseModel):
    """Experiment run results response."""

    id: UUID
    status: str
    expression: Optional[str] = None
    columns: Optional[List[str]] = None
    row_count: Optional[int] = None
    preview_data: Optional[List[Dict[str, Any]]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    as_of_date: Optional[str] = None
    message: Optional[str] = None


# --- Schedule Schemas ---


class ScheduleConfigIn(BaseModel):
    """Schedule configuration input.

    Supports:
    - cron: Standard cron expression (e.g., "0 6 * * *" for 6am daily)
    - interval_seconds: Fixed interval in seconds
    - active: Whether schedule is enabled

    Either cron OR interval_seconds should be provided, not both.
    """

    cron: Optional[str] = Field(
        default=None,
        examples=["0 6 * * *", "0 0 * * MON"],
        description="Cron expression (e.g., '0 6 * * *' for 6am daily)",
    )
    interval_seconds: Optional[int] = Field(
        default=None,
        ge=60,
        examples=[3600, 86400],
        description="Interval in seconds (minimum 60)",
    )
    active: bool = Field(
        default=True,
        description="Whether the schedule is enabled",
    )


class ScheduleConfigOut(BaseModel):
    """Schedule configuration output."""

    cron: Optional[str] = None
    interval_seconds: Optional[int] = None
    active: bool = True
    last_scheduled_at: Optional[str] = None
    next_scheduled_at: Optional[str] = None


class DatasetScheduleOut(BaseModel):
    """Dataset schedule response."""

    id: UUID
    name: str
    schedule: Optional[ScheduleConfigOut] = None
    deployment_id: Optional[str] = None
    orchestrator_kind: Optional[str] = None


# --- Space and User Management Schemas ---


class UserCreate(BaseModel):
    """Create a user with Personal Space."""

    display_name: str = Field(examples=["Alice Smith"])
    email: Optional[str] = Field(default=None, examples=["alice@example.com"])


class UserWithSpaceOut(BaseModel):
    """User creation response with Personal Space info."""

    principal_id: UUID
    display_name: str
    email: Optional[str]
    space_id: UUID
    official_subspace_id: UUID
    staging_subspace_id: UUID


class TeamSpaceCreate(BaseModel):
    """Create a Team Space with owner."""

    name: str = Field(examples=["Quant Research Team"])
    owner_principal_id: UUID = Field(examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"])
    member_principal_ids: Optional[List[UUID]] = Field(
        default=None,
        examples=[
            [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ]
        ],
    )
    description: Optional[str] = Field(default=None, examples=["Our research team"])


class SpaceOut(BaseModel):
    """Space creation response."""

    space_id: UUID
    name: str
    space_kind: str
    official_subspace_id: UUID
    staging_subspace_id: UUID


class CustomSubspaceCreate(BaseModel):
    """Create a custom subspace."""

    name: str = Field(examples=["Experiments"])
    description: Optional[str] = Field(
        default=None, examples=["Custom subspace for experiments"]
    )


class SubspaceOut(BaseModel):
    """Subspace response."""

    id: UUID
    name: str
    subspace_kind: str
    parent_space_id: UUID


class ResourceCopy(BaseModel):
    """Copy a resource to another location."""

    target_parent_id: UUID = Field(
        examples=["9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"],
        description="Target parent resource (usually a Project in user's space)",
    )
    new_name: Optional[str] = Field(
        default=None,
        examples=["My FredPipeline"],
        description="Optional new name for the copy",
    )


class ResourceCopyOut(BaseModel):
    """Resource copy response."""

    id: UUID
    source_id: UUID
    name: str
    type: str
    parent_id: UUID
    owner_principal_id: UUID
    derived_from_id: UUID


# =============================================================================
# Definition Upload Schemas
# =============================================================================


class DefinitionUploadOut(BaseModel):
    """Definition upload response."""

    id: UUID
    name: str
    version: str
    definition_type: str
    code_ref: str
    status: str  # draft | active
    evaluation_status: str  # pending | running | passed | failed | skipped
    artifact_ref: str
    tests_total: Optional[int] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None
    issues: List[str] = Field(default_factory=list)


class DefinitionDeployOut(BaseModel):
    """Definition deploy response."""

    id: UUID
    name: str
    code_ref: str
    status: str


class DefinitionTestRerunOut(BaseModel):
    """Definition test re-run response."""

    id: UUID
    evaluation_status: str
    tests_total: int
    tests_passed: int
    tests_failed: int
    duration_ms: int
    passed: bool
    failures: List[Dict[str, Any]] = Field(default_factory=list)


class DefinitionDetailsOut(BaseModel):
    """Definition upload details response."""

    id: UUID
    name: str
    version: str
    definition_type: str
    code_ref: str
    module_file: str
    test_suite_file: Optional[str] = None
    status: str
    evaluation_status: str
    artifact_ref: str
    original_filename: str
    upload_size_bytes: int
    tests_total: Optional[int] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None
    test_duration_ms: Optional[int] = None
    uploaded_by: str
    uploaded_at: str
    manifest: Dict[str, Any] = Field(default_factory=dict)


class DefinitionListItem(BaseModel):
    """Definition list item response."""

    id: UUID
    name: str
    definition_type: str
    code_ref: Optional[str] = None
    status: str
    category: Optional[str] = None
    version: Optional[str] = None


class DefinitionListOut(BaseModel):
    """Definition list response."""

    items: List[DefinitionListItem]
    next_cursor: Optional[str] = None


# ============================================================================
# Audit and Notification Schemas
# ============================================================================


class AuditLogEntry(BaseModel):
    """Audit log entry with full activity envelope."""

    id: UUID
    tenant_id: UUID
    activity_id: UUID
    envelope: Dict[str, Any]
    processed_at: datetime


class AuditLogPage(BaseModel):
    """Paginated audit log response."""

    items: List[AuditLogEntry]
    next_cursor: Optional[str] = None


class NotificationOut(BaseModel):
    """Notification with embedded activity event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    activity_id: UUID
    activity: Optional[ActivityEventV1] = None
    created_at: datetime
    read_at: Optional[datetime] = None


class NotificationPage(BaseModel):
    """Paginated notification response."""

    items: List[NotificationOut]
    next_cursor: Optional[str] = None
    unread_count: int = 0


class NotificationMarkRead(BaseModel):
    """Mark notification as read/unread."""

    read: bool = True


class NotificationMarkAllReadOut(BaseModel):
    """Response for mark all read operation."""

    marked_count: int


class NotificationPreferenceOut(BaseModel):
    """Notification preference response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    filter_mode: str
    custom_actions: List[str]
    muted: bool
    updated_at: datetime


class NotificationPreferenceUpdate(BaseModel):
    """Update notification preferences."""

    filter_mode: Optional[str] = Field(
        default=None,
        examples=["mutations"],
        description="Filter mode: 'all', 'mutations', or 'custom'",
    )
    custom_actions: Optional[List[str]] = Field(
        default=None,
        examples=[["resource.*", "chat.*"]],
        description="Custom action patterns for 'custom' filter mode",
    )
    muted: Optional[bool] = Field(
        default=None,
        examples=[False],
        description="If true, suppress all notifications",
    )
