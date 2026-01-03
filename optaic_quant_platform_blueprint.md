# OptAIC Quant Research Platform Blueprint (Governance + Pipelines + MLOps)

> Purpose: a governed, self-hosted quant research platform where **everything** (code definitions, configs, datasets, models, runs, approvals, and chat) is a **Resource** with strict **space segregation**, **RBAC**, **share/promotion workflows**, and **audit-traced activity events**.
>
> This document is intentionally **self-contained** so it can be uploaded later as the authoritative description of the system vision and the infrastructure enhancements required before business logic implementation.

---

## 1) Business objectives

OptAIC aims to support:

- **Time-series datasets** and **reference datasets** (vintage/PIT aware).
- **Operators (Ops)** and **DSL Expressions** to transform datasets into new datasets or **signals** with signal specs (e.g., range **[-1, 1]**).
- **Trainable ML modules** treated as “Ops that learn”:
  - ML training
  - model registry
  - inference
  - monitoring (data drift + performance drift + freshness)
  - config-as-code
- A **plugin-first platform**:
  - researchers/engineers (and agents) build new `Pipeline`, `Store`, `Accessor`, `Op`, and `ML` definitions via SDK
  - submission to platform must pass **evaluation + testing** before admission
- All items (definitions + instances + runs) are **governed resources** with sharing, promotions, approvals, and audit trails.
- Communications are first-class: **chat channels are resources** under RBAC; auditors can subscribe as allowed.

---

## 2) Governance rules (spaces, projects, promotion lanes)

### 2.1 Spaces and subspaces

Every tenant contains segregated spaces:

- **Personal Space** (per user)
- **Team Space** (per team)
- **System Space** (global, platform-managed)

Each space has two official subspaces:

- `official` — stable, approved, production-ready
- `staging` — quarantine/review area for incoming shares/promotions and for change proposals

Optional: additional custom subspaces may exist in personal/team spaces, controlled by owner/delegator.

### 2.2 Admin initialization

- Admin creates **users** and **team spaces**.
- On user creation:
  - create the user’s **Personal Space**
  - create default `official` + `staging` subspaces
  - optionally create a “home project”
- Admin creates Team Space and assigns **team owner(s)** from existing users.
  - team owners manage membership and subspace/project governance thereafter.

### 2.3 Projects

Projects are isolation boundaries and organization units:

- Users can create projects only in subspaces where RBAC permits.
- Resource submission (definitions) must occur in **personal projects** (personal space).

### 2.4 Promotion rules

Hard rules:

- **Promotion direction is one-way**:
  - personal → team
  - team → system
- Promotion/share always lands in destination **staging** subspace first.
- Only space owner/delegator can **merge staging → official** (approval-gated).

### 2.5 Promotion includes dependency closure

Promoting/sharing a resource must include its **dependencies** to ensure the promoted artifact functions in destination staging.

Dependencies can include:
- referenced definitions (pipelines/stores/accessors/ops/ml modules)
- upstream datasets (or mapping stubs)
- extension packages and tests
- schema/signature constraints
- run-time requirements metadata

Promotion produces a **PromotionBundle** that captures:
- root resource
- dependency closure list (ordered)
- compatibility checks and test results
- mapping requirements (e.g., missing upstream dataset in destination)

---

## 3) Resource taxonomy (Definitions, Instances, Runs/Versions)

To keep the platform coherent, enforce three tiers:

### 3.1 Definition resources (plugin definitions)

Reusable, versioned, testable building blocks:

| Definition Type | Purpose | Examples |
|----------------|---------|----------|
| `PipelineDef` | ETL, Expression, Training, Inference, Monitoring pipelines | `BloombergPipeline`, `FredPipeline`, `ExpressionPipeline` |
| `StoreDef` | Data persistence strategy | `ParquetStore`, `VirtualCacheStore`, `SQLiteStore` |
| `AccessorDef` | Data retrieval interface | `PITAccessor`, `SnapshotAccessor`, `FieldAccessor` |
| `OpDef` | Primitive operations | `MA`, `Zscore`, `Lag`, `REF`, `DELTA` |
| `OpMacroDef` | Saved DSL expression as reusable op | `MACrossover`, `MomentumScore` |
| `MLModuleDef` | ML model module (trainer, inference, monitor) | `XGBTrainer`, `LSTMPredictor` |
| `PortfolioOptimizerDef` | Portfolio construction algorithm | `MVOOptimizer`, `HRPOptimizer`, `BlackLitterman`, `RiskParity`, `RLOptimizer` |
| `HookDef` | Pre/post hooks for policy, QA gates, notifications | `SchemaValidator`, `AlertNotifier` |

All definitions:
- implement required abstract interfaces
- contain test suite
- are admitted only after evaluation

### 3.2 Instance resources (config-as-code)

Concrete configurations referencing definitions:

| Instance Type | Composed Of | Definition Ref | Notes |
|--------------|-------------|----------------|-------|
| `DatasetInstance` | PipelineInstance + StoreInstance + AccessorInstance | Multiple Defs | Core data entity |
| `SignalInstance` | DatasetInstance + SignalSpec | Inherits from Dataset | Specialized for signals |
| `ModelInstance` | MLModuleDef + datasets + config | `MLModuleDef` | ML model deployment |
| `ExperimentInstance` | Expressions + preview datasets | `OpDef`/`OpMacroDef` | Expression experiments |
| `PortfolioOptimizerInstance` | Constraints + config | `PortfolioOptimizerDef` | Portfolio construction |
| `BacktestInstance` | Assets + signals + date range + config | None (fixed procedure) | Backtest configuration |

**BacktestInstance** is special — no definition needed because the backtest procedure code is fixed. Only the **configuration** varies:
- Assets to trade
- Signals to use (references to SignalInstance resources)
- Date range (start, end, warmup period)
- Rebalance frequency
- Model retrain frequency
- Transaction costs and constraints

**PortfolioOptimizerInstance** references a `PortfolioOptimizerDef` (MVO, HRP, Black-Litterman, Risk-Parity, RL, etc.) and specifies:
- Constraints (max_weight, min_weight, leverage, turnover)
- Risk model configuration
- Lookback windows
- Algorithm-specific parameters

Instances are config-as-code on top of defs + versions:
- `(def_resource_id, def_version_id)` + `config_json`

### 3.3 Runs and immutable versions (provenance backbone)

Executions are first-class:

| Run Type | Parent Instance | Outputs | Notes |
|----------|----------------|---------|-------|
| `PipelineRun` | DatasetInstance | DatasetVersion | Dataset refresh |
| `ExperimentRun` | ExperimentInstance | Preview results | Expression evaluation |
| `TrainingRun` | ModelInstance | ModelVersion + artifacts | ML training |
| `InferenceRun` | ModelInstance | Prediction dataset | ML inference |
| `MonitoringRun` | ModelInstance | Metrics + alerts | Drift detection |
| `BacktestRun` | BacktestInstance | PnL, Sharpe, trades, equity curve | Backtest execution |
| `PortfolioOptimizationRun` | PortfolioOptimizerInstance | Weights, optimization metrics | Portfolio construction |

Outputs and provenance:
- `DatasetVersion` — versioned dataset snapshot
- `ModelVersion` — versioned model artifact
- `LineageEdge` — linking upstream versions → downstream version

Invariant:
> Only Runs create Versions; Versions create Lineage.

**BacktestRun outputs:**
```
BacktestRun
├── metrics_json: {sharpe, sortino, max_drawdown, turnover, calmar}
├── trades_json: [{date, asset, direction, quantity, price}, ...]
├── equity_curve_ref: path to equity curve data
└── lineage: [signal_versions, dataset_versions used]
```

**PortfolioOptimizationRun outputs:**
```
PortfolioOptimizationRun
├── weights_json: {asset: weight, ...}
├── optimization_metrics_json: {objective_value, iterations, convergence}
├── constraints_satisfied: bool
└── timestamp
```

---

## 4) Dataset + pipeline semantics

### 4.1 Pipeline is the universal execution abstraction

Pipeline flavors (all share a common interface):

- **ETL**: external source ingestion (e.g., FRED GDP vintage)
- **EXPRESSION**: DSL transforms datasets → new datasets/signals
- **TRAINING**: reads datasets → produces model artifacts + registry entry
- **INFERENCE**: reads features + model → writes prediction dataset
- **MONITORING**: reads data/preds/realized → writes metrics + alerts

### 4.2 Dataset freshness model

Each DatasetInstance carries schedule metadata:
- expected cadence (regular/irregular)
- watermark logic (event time vs ingestion time)
- grace period
- derived freshness state:
  - `UP_TO_DATE | STALE | MISSING | ERROR`

Freshness changes emit activity events and notifications.

### 4.3 DAG/lineage needs

- Each dataset instance has a lineage graph.
- Execution uses a DAG:
  - tasks: extract/transform/load/train/infer/validate/monitor
- Support both:
  - bulk backfill
  - incremental daily updates

### 4.4 Flow Execution Resources (Execution Framework)

**Key Insight**: Instance Resources and Flow Execution Resources are paired. When an Instance is created, its corresponding Flow Execution Resources are automatically created and registered with the orchestrator (Prefect).

#### 4.4.1 Flow Execution vs Runs

| Concept | What It Is | Lifecycle |
|---------|-----------|-----------|
| **Flow Execution Resource** | Registered Prefect deployment | Created when Instance is created |
| **Run** | Each execution of a Flow | Created when flow is triggered |

- **Flow Execution Resources** are **static** - they define WHAT can be executed
- **Runs** are **dynamic** - they represent WHEN something was executed and results

#### 4.4.2 Instance ↔ Flow Pairing

Definitions specify which Flow Execution Resources to create for each Instance type:

| Instance Type | Flow Execution Resources (embedded) | Purpose |
|--------------|-------------------------------------|---------|
| `DatasetInstance` | `bulk_run_deployment_id`, `incremental_deployment_id` | Full reload, incremental update |
| `ModelInstance` | `training_deployment_id`, `inference_deployment_id`, `monitoring_deployment_id` | Training, inference, monitoring |
| `BacktestInstance` | `backtest_deployment_id` | Backtest execution |
| `PortfolioOptimizerInstance` | `optimization_deployment_id` | Portfolio optimization |

Flow Execution Resources are **embedded** in Instance tables (Option B), but tracked in the activity system for audit and guardrails.

#### 4.4.3 Instance Creation Initializes Flows

```
User creates: DatasetInstance("daily_prices")
     │
     ├── Definition says: "Create bulk_run and incremental flows"
     │
     ├── System creates:
     │   ├── Prefect Deployment: "daily_prices.bulk_run"
     │   │   └── code_ref → PipelineBulkRunFlow method
     │   │
     │   └── Prefect Deployment: "daily_prices.incremental"
     │       └── code_ref → PipelineIncrementalFlow method
     │
     └── Instance stores:
         ├── bulk_run_deployment_id: "prefect-deploy-abc"
         └── incremental_deployment_id: "prefect-deploy-def"
```

#### 4.4.4 Lineage is Flow-to-Flow

Lineage dependencies track **Flow Execution Resources**, not just Instances:

```
resource_lineage:
  upstream: raw_prices.incremental_flow
  downstream: daily_prices.incremental_flow
  edge_kind: "data_dependency"
```

This enables:
- Lineage checker to verify upstream flows' last run status
- Blocking downstream execution if upstream is stale/error
- Real-time status updates via activity subscription

#### 4.4.5 Status Aggregation

Each Flow Execution Resource has its own status (derived from latest run):

```
daily_prices.bulk_run       → status: "success", last_run: 2024-01-01
daily_prices.incremental    → status: "running", last_run: 2024-01-15
```

Instance status is **aggregated** from its flows:
- If ALL flows are SUCCESS → Instance status = READY
- If ANY flow is ERROR → Instance status = ERROR
- If ANY flow is STALE → Instance status = STALE

Aggregation logic is defined in Definition's `status_aggregation_contract`.

#### 4.4.6 Real-Time Status Updates (Observer Pattern)

Flow Execution Resources **subscribe** to upstream flows' activities:

```
daily_prices.incremental subscribes to: activity:flow:{raw_prices.incremental.id}

When raw_prices.incremental run completes:
  1. Activity emitted: "flow.run_completed"
  2. Centrifugo broadcasts to subscribers
  3. daily_prices.incremental receives notification
  4. Lineage status cache updated
  5. (Optional) Auto-trigger downstream flow if configured
```

Subscription rules are defined in Definition's `subscription_contracts`.

#### 4.4.7 Execution Time Flow

```
User/Schedule triggers: "daily_prices.incremental" flow
     │
     ├── 1. Lineage Engine checks upstream flows' statuses
     │       ├── raw_prices.incremental → last run SUCCESS? ✓
     │       └── If not ready → block/warn per guardrail contract
     │
     ├── 2. Guardrails Engine validates at run.submit gate
     │       └── Contracts from Definition (freshness, schema, etc.)
     │
     ├── 3. Prefect executes the flow
     │
     ├── 4. Run Resource created (the activity/action)
     │       └── PipelineRun { flow_deployment_id, started_at, status }
     │
     ├── 5. Audit Engine logs activity
     │       └── ActivityEnvelope { action: "flow.run_completed" }
     │
     ├── 6. Activity broadcasted to subscribers via Centrifugo
     │       └── Downstream flows get notified
     │
     └── 7. Status updated (aggregated to Instance if needed)
```

#### 4.4.8 Definition Specifies Flow Behavior

Definitions contain flow specifications:

```python
class PipelineDefinition:
    # Flow specifications (which flows to create for instances)
    flow_specs = [
        FlowSpec(
            name="bulk_run",
            code_ref="PipelineBulkRunFlow",
            description="Full history reload",
        ),
        FlowSpec(
            name="incremental",
            code_ref="PipelineIncrementalFlow",
            description="Append new data",
        ),
    ]

    # Lineage contract (how to check upstream dependencies)
    lineage_contracts = [
        LineageContract(
            edge_kind="data_dependency",
            check_freshness=True,
            block_if_stale=True,
        ),
    ]

    # Status aggregation rule
    status_aggregation_contract = {
        "rule": "all_success_means_ready",
        "priority": ["incremental", "bulk_run"],
    }

    # Subscription rules for real-time updates
    subscription_contracts = [
        SubscriptionContract(
            subscribe_to="upstream.incremental",
            on_event="flow.run_completed",
            action="update_lineage_cache",
        ),
    ]
```

#### 4.4.9 ModelInstance Multi-Flow Example

```
ModelInstance("xgb_predictor")
├── training_deployment_id → TrainingFlow
│   ├── Depends on: training_dataset.incremental_flow
│   ├── Outputs: MLflow Experiment Run, model artifact
│   └── On success: Register model version
│
├── inference_deployment_id → InferenceFlow
│   ├── Depends on: model_version (from training)
│   ├── Depends on: inference_dataset.incremental_flow
│   └── Outputs: Predictions dataset
│
└── monitoring_deployment_id → MonitoringFlow
    ├── Depends on: inference outputs
    ├── Outputs: Drift reports, performance metrics
    └── Links to: Evidently project
```

#### 4.4.10 Extensibility for User Plugins

While system provides base flows for standard resource types, Definitions can:
- Add custom flows via `extra_flow_specs`
- Override flow behavior via hooks
- Define custom lineage contracts
- Specify custom status aggregation rules

SDK exposes:
- `BaseFlowSpec` protocol for defining custom flows
- `@flow_hook` decorator for customizing behavior
- `LineageContract` for custom dependency rules

---

## 5) Unified event, audit, and communication backbone

### 5.1 Activity events and outbox

All mutations emit canonical ActivityEvent:
- actor (user/agent)
- resource
- action
- payload
- correlation_id
- targets (resource channel, inbox, auditor stream)

Use outbox pattern for reliable publishing to realtime notification channels.

### 5.2 Audit

Auditors subscribe to events only via RBAC (no hard-coded superuser).
Audit trails store:
- what changed
- who changed it
- why (optional)
- approval decisions

### 5.3 Chat channels as resources

Channels are resources with:
- RBAC
- ownership/moderation roles
- ability to link to projects/datasets/runs/approvals
- mentions triggering notifications and agent workflows

---

## 6) Guardrails Framework (Contract-Driven Validation)

OptAIC enforces **guardrails** at all lifecycle gates to ensure configured resources conform to declared contracts before they can be promoted or executed in production.

### 6.0 Architecture: Law vs Police

**Definition Resources = The Law**
- Definitions contain contracts, schemas, and compatibility rules
- These define WHAT must be validated

**Guardrails Engine = The Police**
- Reads contracts FROM Definition Resources
- Enforces them at gates (instance creation, run execution, data write, promotion)
- Does NOT define contracts—it enforces them

```
┌─────────────────────────────────────────────────────────────────┐
│           DEFINITION RESOURCE (The Law)                          │
│  ├── interface_spec        # Abstract interface                  │
│  ├── input_schema          # Expected inputs                     │
│  ├── output_schema         # Expected outputs                    │
│  ├── compatibility_rules   # What can connect upstream/downstream│
│  └── guardrail_contracts   # Validation rules                    │
│      ├── signal.bounds: {min: -1, max: 1}                       │
│      ├── pit.policy: {knowledge_date_required: true}            │
│      └── dataset.schema: {columns: [...]}                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           GUARDRAILS ENGINE (The Police)                         │
│  Reads contracts FROM Definitions, enforces at gates:            │
│  ├── Gate 1: Instance Creation (validate config + compatibility) │
│  ├── Gate 2: Run Execution (validate inputs match schema)        │
│  ├── Gate 3: Data Write (validate outputs in real-time)          │
│  └── Gate 4: Promotion/Merge (all contracts must pass)           │
└─────────────────────────────────────────────────────────────────┘
```

### 6.1 Core Concepts

| Concept | Description |
|---------|-------------|
| **Definition Contracts** | Validation rules embedded in Definition Resources (the "law"). |
| **Guardrails Engine** | The enforcement system that reads and validates contracts (the "police"). |
| **Compatibility Rules** | Rules in Definitions specifying valid upstream/downstream resource types. |
| **ValidationReport** | The output of every guardrail evaluation—stored and emitted as an activity event. |

### 6.2 Lifecycle Gates

Guardrails are evaluated at these platform gates:

**Resource lifecycle:**
- `resource.create`
- `resource.update`
- `definition.submit` (evaluation admission gate)

**Governance lifecycle:**
- `promotion.request` (dependency-closure checks)
- `merge.staging_to_official` (approval gate)

**Execution lifecycle:**
- `run.submit` (before starting execution)
- `run.start` (optional runtime checks)
- `run.complete` (output validation)

### 6.3 Enforcement Policy (Staging vs Official)

| Subspace Kind | Default Policy | Behavior |
|---------------|----------------|----------|
| `staging` | **WARN** | Validation issues are logged; operation proceeds. |
| `official` | **BLOCK** | Validation errors halt the operation. |

This keeps iteration fast in staging while ensuring official is safe and compliant.

Policy can be further refined:
- Team staging stricter than personal staging
- Certain actions always block (e.g., merge-to-official)
- Admin-configurable enforcement by contract kind

### 6.4 ValidationReport Schema

Every evaluation produces a persisted report:

```
ValidationReport:
  id: UUID
  scope: resource | run | promotion | merge
  target_id: UUID (resource_id / run_id / promotion_id / merge_id)
  ok: bool
  enforced_as: warn | block
  issues: List[ValidationIssue]
    - code: str (e.g., "BOUNDS_EXCEEDED")
    - severity: error | warning
    - message: str
    - path: str (JSON path to offending field)
  contract_hashes: List[str]
  correlation_id: UUID (links to broader workflows)
  created_at: datetime
```

### 6.5 Activity Events for Audit

Every guardrails evaluation emits ActivityEvent via the outbox:

- `guardrails.validated` — always emitted
- `guardrails.blocked` — emitted when blocked by policy

Payload includes:
- `report_id`
- `target_id`, `scope`
- `ok`, `enforced_as`
- issue counts (errors/warnings)
- `correlation_id`

Auditor subscriptions are RBAC-driven; no hard-coded superuser access.

### 6.6 Contract Kinds (Examples for Future Implementation)

| Contract Kind | Purpose | Example Config |
|---------------|---------|----------------|
| `dataset.schema` | Arrow schema validation | `{"expected_columns": [...]}` |
| `dataset.freshness` | Schedule + grace period | `{"expected_cadence": "daily", "grace_hours": 6}` |
| `signal.bounds` | Range + index constraints | `{"min": -1, "max": 1, "allow_nan": false}` |
| `pit.policy` | No-lookahead constraints | `{"knowledge_date_required": true}` |
| `portfolio.constraints` | Weights/leverage/turnover | `{"max_weight": 0.1, "max_leverage": 2.0}` |
| `execution.policy` | Order types, limits, venues | `{"allowed_order_types": ["limit"]}` |
| `promotion.closure` | Dependency completeness | `{"require_all_refs": true}` |

> **Note:** These are placeholders for future domain logic. The guardrails framework is domain-agnostic; business contracts are added incrementally.

### 6.7 How Guardrails Integrate with Promotion Bundles

Promotion workflows include guardrails at multiple points:

```
1. User requests promotion (personal → team)
2. Guardrails evaluate: promotion.closure contract
   → Check dependency closure completeness
   → Check mapping requirements (missing upstreams)
3. If staging: WARN on issues, proceed
4. Resource lands in team/staging
5. Delegator reviews and approves merge to official
6. Guardrails evaluate at merge gate: all attached contracts
   → If official: BLOCK on errors
7. If passed: Resource is now in team/official
```
p[devui]
---

## 7) Infrastructure enhancements required next

Before implementing full domain logic, enhance infrastructure to support:

1) **Workflow orchestration / DAG execution**
2) **ML lifecycle**: training, registry, inference, monitoring
3) **Artifacts & metadata stores** that survive `pip upgrade`
4) **Unified “optaic server” supervisor** that can start/stop the full stack on Windows
5) **Version tracking** of infra components (sidecars) and automatic upgrades
6) **SDK hooks** for researchers/agents to submit defs and instances

---

## 8) Recommended Python-native tech stack (Windows-friendly, integratable into `optaic server`)

This is designed for two modes:

- **Embedded mode (default)**: zero external dependencies, all local, suitable for single-machine usage and small-team testing.
- **Production mode**: externalized stores/services, scalable and resilient.

### 8.1 Workflow orchestration / DAG execution

**Recommendation: Prefect (self-hosted server in embedded mode)**  
Rationale:
- Prefect supports **SQLite by default** for lightweight deployments and runs DB migrations automatically on server start. citeturn0search2
- It provides flows/tasks, retries, schedules, concurrency limits, and event hooks—ideal for dataset refresh, training runs, monitoring jobs.

How to integrate:
- Add an internal abstraction `OrchestratorAdapter`:
  - `LocalOrchestrator` (simple in-process DAG executor; NetworkX/Toposort + thread/process pool)
  - `PrefectOrchestrator` (submit flows to Prefect)
- In embedded mode:
  - `optaic server --with-prefect` starts Prefect server as a subprocess
  - Configure Prefect DB to live in `DATA_DIR/prefect/`
- In prod:
  - point to external Prefect server + Postgres

### 8.2 ML tracking + registry

**Recommendation: MLflow Tracking Server + Model Registry**  
Rationale:
- MLflow supports relational backends including **SQLite**, and SQLite is the default backend store when you start MLflow without specifying a backend store URI. citeturn0search0turn0search1
- MLflow server is easily run as a subprocess (HTTP server) and provides a UI.

How to integrate:
- Keep OptAIC as the governance “source of truth”:
  - OptAIC `TrainingRun` exists regardless of MLflow.
- Add optional MLflow sync:
  - create a matching MLflow run per OptAIC TrainingRun (tags contain resource ids/versions)
  - register model versions in MLflow model registry
  - store artifacts in local `DATA_DIR/mlflow/artifacts` in embedded mode
- In embedded mode:
  - `optaic server --with-mlflow` starts `mlflow server` on localhost with sqlite backend in DATA_DIR
- In prod:
  - external DB (Postgres/MSSQL) + remote artifact store (S3/MinIO/Azure) as needed

### 8.3 Monitoring and data quality

Lightweight, Windows-friendly options (can be embedded):

- **Data validation**: Pandera (schema checks), optionally Great Expectations for richer suites.
- **Drift/performance monitoring**: Evidently (batch drift reports), WhyLogs (profiling), plus simple custom rules.
- Integrate monitoring as pipelines:
  - monitoring pipelines emit MetricEvents and AlertEvents (as activities)

### 8.4 Data processing and storage

- **Primary file format**: Parquet (vintage partitions)
- **Local analytics**: DuckDB embedded for fast local PIT queries and research notebooks
- **Stores**: implement StoreDef with:
  - ParquetStore (partitioned by date/vintage)
  - VirtualStore (compute-on-read cache)
- **Accessors**: PITAccessor, SnapshotAccessor, LatestAccessor

### 8.5 Scheduling

- Prefer Prefect schedules in orchestrated mode.
- In minimal embedded mode without Prefect:
  - APScheduler for cron-like schedules (dataset refresh / monitoring)
  - schedule metadata stored on DatasetInstance

### 8.6 Plugin system and extension admission

- Plugin loading: `importlib.metadata` entry points + a thin registry layer
- Hook system: `pluggy` pattern or internal hooks
- Evaluation harness:
  - `pytest` for tests
  - static checks: ruff
- Admission workflow:
  - DefinitionSubmission resource + EvaluationRun pipeline
  - owner/delegator approvals for merge to official

### 8.7 Realtime notifications + messaging

- Continue using Centrifugo for realtime channels (chat, activity feeds), managed by optaic supervisor.
- Redis stays optional (e.g., for scaling / Centrifugo redis engine), default off.

### 8.8 Packaging and upgrades (survive `pip upgrade`)

- Persist all state in a stable `DATA_DIR` (not inside wheel).
- Auto-run DB migrations on startup.
- Track installed infra versions (centrifugo, optional redis, prefect server, mlflow server) in `DATA_DIR/state/installed.json`.
- Provide:
  - `optaic upgrade --dry-run / --apply / --restart`
  - GUI “System → Updates” uses the same upgrade job runner
- For package distribution on-prem, use local pypiserver with staging/uat/prod lanes.

Security note for pip:
- pip warns that using `--extra-index-url` can be unsafe due to dependency confusion; prefer using your internal index as the primary and tightly control package names/versioning. citeturn1search9
- pypiserver supports `--disable-fallback` to avoid redirecting to public PyPI for missing packages. citeturn1search2

### 8.9 Unified ML SDK (`optaic.mlops`)

**Key Deliverable**: A unified Python SDK that wraps MLOps infrastructure into a single cohesive package, enabling researchers to build ML model definitions using native ML libraries while leveraging platform infrastructure seamlessly.

#### Design Goals

1. **Unified Interface** — Single import for all MLOps infrastructure (tracking, registry, monitoring, orchestration)
2. **Native ML Library Support** — Users write models using sklearn, PyTorch, XGBoost, etc. with minimal boilerplate
3. **Seamless Dev-to-Ops** — Same code works in local notebooks and production pipelines
4. **Platform Integration** — Automatic activity emission, lineage tracking, and governance compliance

#### SDK Architecture

```
optaic.mlops
├── tracking          # Experiment tracking (wraps MLflow)
│   ├── log_params()
│   ├── log_metrics()
│   ├── log_artifacts()
│   └── autolog()     # Framework-specific auto-logging
│
├── registry          # Model versioning (wraps MLflow Model Registry)
│   ├── register_model()
│   ├── load_model()
│   ├── transition_stage()
│   └── get_latest_version()
│
├── monitoring        # Data & performance monitoring (wraps Evidently)
│   ├── DataDriftMonitor
│   ├── PerformanceMonitor
│   ├── TestSuite
│   └── AlertManager
│
├── pipeline          # Orchestration (wraps Prefect)
│   ├── @task
│   ├── @flow
│   ├── schedule()
│   └── run_now()
│
├── data              # PIT-aware data access
│   ├── load_dataset()
│   ├── write_dataset()
│   └── DatasetRef
│
└── base              # Base classes for model definitions
    ├── BaseModel
    ├── BaseTrainer
    ├── BasePredictor
    └── BaseMonitor
```

#### Usage Patterns

**Researcher writes model using native libraries + SDK infrastructure:**

```python
from optaic.mlops import tracking, registry, monitoring, pipeline
from optaic.mlops.base import BaseModel, BaseTrainer
from optaic.mlops.data import load_dataset, DatasetRef

import xgboost as xgb  # Native ML library
import pandas as pd

class XGBSignalModel(BaseModel):
    """User defines model using native XGBoost."""

    def __init__(self, params: dict):
        self.model = xgb.XGBRegressor(**params)

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.model.fit(X, y)

    def predict(self, X: pd.DataFrame) -> pd.Series:
        return pd.Series(self.model.predict(X))


class XGBTrainer(BaseTrainer):
    """Training with automatic tracking + monitoring."""

    @tracking.autolog()  # Auto-logs params, metrics, artifacts
    def train(self, model: XGBSignalModel, train_data: DatasetRef) -> str:
        # Load PIT-correct data via SDK
        df = load_dataset(train_data, as_of=self.as_of_date)
        X, y = df.drop("target"), df["target"]

        # Train using native library
        model.fit(X, y)

        # Validate output bounds (SDK enforces guardrails)
        preds = model.predict(X)
        monitoring.validate_signal_bounds(preds, min=-1, max=1)

        # Register to model registry
        model_uri = registry.register_model(
            model=model,
            name=self.model_instance_name,
            metrics={"ic": self.compute_ic(y, preds)}
        )
        return model_uri
```

**Pipeline definition using SDK orchestration:**

```python
from optaic.mlops import pipeline

@pipeline.task
def load_features(dataset_ref: str, as_of: str):
    return load_dataset(dataset_ref, as_of=as_of)

@pipeline.task
def train_model(features, model_config):
    trainer = XGBTrainer(config=model_config)
    return trainer.train(XGBSignalModel(model_config), features)

@pipeline.task
def run_inference(model_uri: str, features):
    model = registry.load_model(model_uri)
    return model.predict(features)

@pipeline.flow
def signal_generation_pipeline(as_of: str):
    features = load_features("SPX_Features", as_of)
    model_uri = train_model(features, {"max_depth": 6})
    signals = run_inference(model_uri, features)
    return signals

# Schedule weekly retraining
pipeline.schedule(signal_generation_pipeline, cron="0 0 * * SUN")
```

#### Backend Abstraction

The SDK abstracts over embedded vs. production backends:

| Component | Embedded Mode | Production Mode |
|-----------|---------------|-----------------|
| `tracking` | MLflow + SQLite in DATA_DIR | MLflow + Postgres + S3 |
| `registry` | Local MLflow registry | Remote MLflow registry |
| `monitoring` | Evidently local reports | Evidently + metrics DB |
| `pipeline` | LocalOrchestrator (in-process) | Prefect server |

Configuration is automatic based on `optaic server` startup flags:

```bash
optaic server                          # Embedded mode (SQLite, local)
optaic server --with-mlflow --with-prefect  # Production components enabled
```

#### Integration with Platform Governance

The SDK automatically integrates with OptAIC governance:

```python
# Activity emission (automatic)
# - Every training run emits TrainingActivity
# - Every inference emits InferenceActivity
# - Every model registration emits ModelRegisteredActivity

# Lineage tracking (automatic)
# - Dataset versions linked to model versions
# - Model versions linked to prediction datasets

# Guardrails enforcement (via SDK validators)
monitoring.validate_signal_bounds(signals, min=-1, max=1)
monitoring.validate_no_lookahead(df, knowledge_date_col="knowledge_date")
monitoring.validate_data_quality(df, schema=expected_schema)
```

This unified SDK enables researchers to focus on ML logic while the platform handles tracking, versioning, monitoring, orchestration, and governance automatically.

---

## 9) How it all fits into `optaic server`

### 9.1 Suggested `optaic server` flags (embedded default)

- `optaic server`
  - API + worker + agent + Centrifugo
  - SQLite DB
  - local artifacts
- Optional switches:
  - `--with-prefect` : start Prefect server subprocess and configure adapter
  - `--with-mlflow`  : start MLflow server subprocess for tracking/registry UI
  - `--with-redis`   : start Redis (Windows embedded) and switch Centrifugo engine

All of these are managed in the same supervisor, tracked in installed.json, and upgraded via the same upgrade engine.

### 9.2 Adapter-driven integration (keeps business logic clean)

Define internal interfaces:
- `OrchestratorAdapter` (submit flow / schedule / query state)
- `RegistryAdapter` (register model / fetch versions / stage transitions)
- `ArtifactStoreAdapter` (put/get artifacts)
- `MonitoringAdapter` (log metrics, drift reports)

Then implement:
- embedded adapters (local filesystem + sqlite)
- Prefect adapter (workflow)
- MLflow adapter (registry/metrics)

This gives you “swapability” without rewriting domain logic.

---

## 10) Next steps (recommended implementation order)

1) Implement orchestrator abstraction + minimal LocalOrchestrator DAG executor.
2) Integrate Prefect as optional (`--with-prefect`) and map:
   - Dataset refresh → Prefect flows
   - Training runs → Prefect deployments (optional)
3) Integrate MLflow as optional (`--with-mlflow`) and map:
   - TrainingRun → MLflow run
   - ModelVersion → MLflow model registry entry
4) Define Run/Version/Lineage schema and connect to dataset instances.
5) Implement promotion bundles with dependency closure and automated staging validation pipelines.
6) Add monitoring pipelines + dataset freshness state machine + alerting rules.

---

## 11) Two-Tier Resource Model: Definitions vs Instances

### 11.1 Core Concept

OptAIC separates **what** (definitions) from **how** (instances):

```
Definition (Plugin)         Instance (Config)              Run (Execution)
─────────────────          ──────────────────             ────────────────
BloombergPipelineDef   →   SPX_OHLCV_Dataset          →   Daily refresh run
  (code + interface)         (config + refs)               (execution + version)
```

### 11.2 Definitions are Plugins

Definitions are **reusable building blocks** submitted as plugins:

| Definition Type | What It Defines | Examples |
|----------------|-----------------|----------|
| `PipelineDef` | Data ingestion/transformation logic | `BloombergPipeline`, `FredPipeline`, `ExpressionPipeline` |
| `StoreDef` | Data persistence strategy | `ParquetStore`, `VirtualCacheStore` |
| `AccessorDef` | Data retrieval interface | `PITAccessor`, `FieldAccessor`, `SnapshotAccessor` |
| `OpDef` | Primitive operation | `MA`, `Zscore`, `Lag` |
| `OpMacroDef` | Saved DSL expression | `MACrossover`, `MomentumScore` |
| `MLModuleDef` | ML model wrapper | `XGBTrainer`, `LSTMPredictor` |

**Definition Development Flow:**
```
1. Developer writes code implementing abstract interface
2. Developer submits via SDK to personal/staging
3. EvaluationRun executes: pytest, ruff, interface checks
4. If passed → available for promotion
5. Promote to team/system → merge to official after approval
6. Definition is now a registered plugin
```

### 11.3 Instances are Configurations

Instances are **concrete usages** of definitions with specific config:

```python
# Example: SPX OHLCV Dataset Instance
DatasetInstance(
    name="SPX_OHLCV_Daily",
    pipeline=PipelineInstanceRef(
        def_id="bloomberg-pipeline-def",
        def_version="1.2.0",
        config={"ticker": "SPX Index", "fields": ["PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST", "VOLUME"]}
    ),
    store=StoreInstanceRef(
        def_id="parquet-store-def",
        config={"partition_by": "year", "compression": "snappy"}
    ),
    accessor=AccessorInstanceRef(
        def_id="pit-accessor-def",
        config={"knowledge_date_col": "knowledge_date"}
    ),
    schedule={"cron": "0 18 * * 1-5", "timezone": "America/New_York"}
)
```

**Instance Creation Flow:**
```
1. User selects approved definitions from registry
2. User configures instance via SDK or WebUI
3. Guardrails validate config against definition contracts
4. Submit to personal/staging
5. Promote to team/system for shared use
6. Instance is orchestrated for execution
```

### 11.4 Composable Datasets

Datasets can compose other datasets:

```
External Data                    Derived Signals                   Portfolio
────────────                    ───────────────                   ─────────
BloombergPipeline               ExpressionPipeline                PortfolioConstructor
    │                               │                                  │
    ▼                               ▼                                  ▼
SPX_OHLCV_Dataset    ──────►   SPX_MA_Signal_Dataset  ──────►   SPX_Momentum_Portfolio
    │                               │                                  │
ParquetStore                    VirtualCacheStore                 ParquetStore
PITAccessor                     FieldAccessor                     PITAccessor
```

**DAG Execution:**
- Upstream datasets refresh first
- Downstream datasets compute after upstreams complete
- PIT accessors ensure no lookahead bias at any step

---

## 12) SDK Usage Patterns

### 12.1 For Definition Developers (Platform Engineers)

```python
from optaic import SDK

sdk = SDK()

# Submit new pipeline definition
submission = await sdk.definitions.submit(
    kind="pipeline",
    name="fred-pipeline",
    code_path="./fred_pipeline/",
    tests_path="./tests/",
    interface="OptAIC.PipelineInterface.v1"
)

# Check evaluation status
result = await sdk.definitions.get_evaluation(submission.id)
print(result.status, result.issues)

# Promote to team
await sdk.promotions.request(
    resource_id=submission.resource_id,
    target_space="team:quant-research"
)
```

### 12.2 For Instance Creators (Quant/Data Users)

```python
from optaic import SDK

sdk = SDK()

# List available pipeline definitions
pipelines = await sdk.registry.list_definitions(kind="pipeline")

# Create dataset instance using definitions
dataset = await sdk.instances.create_dataset(
    name="FRED_GDP_Vintage",
    pipeline_def="fred-pipeline",
    pipeline_config={"series_id": "GDP", "vintage_dates": True},
    store_def="parquet-store",
    store_config={"partition_by": "vintage_date"},
    accessor_def="pit-accessor",
    schedule={"cron": "0 9 * * 1"}
)

# Submit for orchestration
await sdk.instances.submit(dataset.id)

# Query data via accessor
data = await sdk.data.query(
    dataset_id=dataset.id,
    as_of_date="2024-01-15",
    knowledge_date="2024-01-15"  # PIT query
)
```

### 12.3 For Experiment Workflows

```python
# Quick expression experiment (not persisted)
result = await sdk.experiments.run_expression(
    expression="zscore(lag(close, 20) / close - 1)",
    input_datasets=["SPX_OHLCV_Daily"],
    date_range=("2020-01-01", "2024-01-01")
)

# Persist as OpMacro definition if good
if result.sharpe > 1.0:
    await sdk.definitions.submit(
        kind="op_macro",
        name="momentum-zscore",
        expression=result.expression,
        tests="auto"  # Generate tests from experiment
    )
```

---

## 13) Platform Development vs User Development

### 13.1 Platform Team Responsibilities

Build the **skeleton** with:
- Abstract interfaces for each definition type
- Base implementations as reference
- Minimal "out of box" definitions in system/official
- Guardrails contracts for validation
- SDK and WebUI for submission/configuration

### 13.2 Quant/Data Team Responsibilities

Extend the platform with:
- New definition plugins (BloombergPipeline, custom expressions)
- Configured instances (specific datasets, signals)
- Experiment workflows
- Analysis and reporting

### 13.3 Governance Throughout

Both follow the same governance:
```
personal/staging → personal/official → team/staging → team/official → system/staging → system/official
```

All actions emit activities. All promotions require approval.

---

## 14) MLOps Architecture (Trainable Ops + Model Lifecycle)

### 14.1 MLOps Overview

**MLOps** is the system for managing **trainable Ops** — ML models that learn from datasets and are registered as a sub-type of Ops for dataset transformation. Unlike static operators, trainable ops require:
- Training runs to produce model artifacts
- Model registry for version management
- Inference endpoints for predictions
- Monitoring for data drift and performance degradation

**Recommended Tech Stack:**

| Component | Tool | License | Purpose |
|-----------|------|---------|---------|
| Experiment Tracking | **MLflow** | Apache-2.0 | Log params, metrics, artifacts; model registry |
| Data Drift Detection | **Evidently** | Apache-2.0 | Feature distribution monitoring, drift alerts |
| Performance Monitoring | **Evidently** | Apache-2.0 | Model accuracy tracking, degradation detection |
| Data Validation | **Evidently Test Suites** | Apache-2.0 | CI/CD quality gates, pre-training validation |
| Data Profiling | **WhyLogs** (optional) | Apache-2.0 | Lightweight statistical profiling |

> Note: Deepchecks was evaluated but not recommended due to AGPL licensing concerns and limited production scalability in OSS version.

### 14.2 ML Model Categories

OptAIC supports these specialized ML model categories:

| Category | Purpose | Typical Inputs | Outputs |
|----------|---------|----------------|---------|
| **Signal Model** | Generate alpha signals from features | Feature datasets | Signal dataset ([-1, 1] range) |
| **Macro Regime Model** | Classify market regimes | Macro/market indicators | Regime labels/probabilities |
| **Relevance Model** | Score feature/signal importance | Features + target | Relevance scores |
| **Signal Combining Model** | Combine multiple signals | Multiple signal datasets | Combined signal |
| **Signal Filtering Model** | Filter/rank signals | Signals + features | Filtered signal set |

### 14.3 ML Model Definition Structure

ML Model Definition is more complex than other plugin definitions. It contains **five code components**:

```
MLModelDef/
├── model/                    # ML Model Source Code
│   ├── __init__.py
│   ├── architecture.py       # Model architecture/class
│   └── config.py             # Model hyperparameters schema
│
├── training/                 # Training/Evaluation Source Code
│   ├── __init__.py
│   ├── trainer.py            # Training loop, loss, optimizer
│   ├── evaluator.py          # Evaluation metrics, validation
│   └── config.py             # Training config schema
│
├── inference/                # Inference Source Code
│   ├── __init__.py
│   ├── predictor.py          # Prediction interface
│   └── batch_inference.py    # Batch prediction for datasets
│
├── monitoring/               # Data & Performance Monitoring Source Code
│   ├── __init__.py
│   ├── data_monitor.py       # Input data drift detection
│   └── perf_monitor.py       # Model performance tracking
│
├── tests/                    # Test Suite
│   ├── test_model.py
│   ├── test_training.py
│   ├── test_inference.py
│   └── test_monitoring.py
│
└── docs/                     # Documentation
    ├── README.md
    └── API.md
```

### 14.4 MLOps Center (UI Architecture)

The MLOps Center is the **real instance hub** for ML models, analogous to how Dataset Inventory contains real dataset instances. It has **two views**:

#### View 1: Model Instance View
Displays registered model instances with their configurations:
- Model definition reference (which MLModelDef)
- Hooked-up datasets (training data, features)
- Configuration and hyperparameters
- Metadata (owner, creation date, tags)
- Current active model version

#### View 2: Model Execution/Operation View
Displays operational aspects of model instances:

| Section | Purpose | Contents |
|---------|---------|----------|
| **Model Training** | Trigger and monitor training runs | Training history, metrics, hyperparameter logs |
| **Model Registry** | Version management | Model versions, stage transitions (staging→production), artifact links |
| **Inference Endpoint** | Serve predictions | Endpoint status, latency metrics, request logs |
| **Data Monitoring** | Detect input drift | Feature distributions, schema changes, freshness |
| **Performance Monitoring** | Track model degradation | Prediction accuracy, realized vs predicted, drift alerts |

### 14.5 Model Instance Composition

A Model Instance references a MLModelDef and composes datasets:

```python
ModelInstance(
    name="SPX_Signal_Model_v1",
    model_def=MLModuleDefRef(
        def_id="xgb-signal-model-def",
        def_version="2.1.0"
    ),
    training_datasets=[
        DatasetInstanceRef("SPX_Features_Daily"),
        DatasetInstanceRef("SPX_Returns_Daily")
    ],
    inference_datasets=[
        DatasetInstanceRef("SPX_Features_Daily")
    ],
    output_dataset=DatasetInstanceRef("SPX_Alpha_Signal"),
    config={
        "target_col": "fwd_return_5d",
        "feature_lag": 1,
        "train_window": 252 * 5
    },
    schedule={
        "training": {"cron": "0 0 * * 0"},  # Weekly retrain
        "inference": {"cron": "0 18 * * 1-5"}  # Daily inference
    }
)
```

### 14.6 Training → Inference → Monitoring Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        MLOps Lifecycle Pipeline                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐ │
│  │   Training   │     │   Registry   │     │       Inference          │ │
│  │   Pipeline   │────►│              │────►│       Pipeline           │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────┘ │
│         │                    │                         │                │
│         ▼                    ▼                         ▼                │
│  TrainingRun          ModelVersion            InferenceRun              │
│  - metrics            - artifact              - predictions             │
│  - hyperparams        - stage                 - latency                 │
│  - eval results       - lineage               - dataset version         │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Monitoring Pipeline                             │   │
│  │  ┌─────────────────────┐    ┌─────────────────────────────────┐   │   │
│  │  │   Data Monitoring   │    │   Performance Monitoring        │   │   │
│  │  │  - feature drift    │    │  - prediction accuracy          │   │   │
│  │  │  - schema changes   │    │  - realized vs predicted        │   │   │
│  │  │  - data freshness   │    │  - degradation alerts           │   │   │
│  │  └─────────────────────┘    └─────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 15) Signal Hub Architecture

### 15.1 Signal Hub Overview

**Signal Hub** is a specialized subset of datasets where each dataset is designated as a **Signal**. Signals are datasets with:
- Strict value constraints (typically [-1, 1] range)
- Integration requirements (data pipeline hooks)
- Backtesting procedures attached

### 15.2 Signal Registration

When a dataset is added to Signal Hub, it requires:

1. **Signal Spec Validation**
   - Value range bounds (e.g., min=-1, max=1)
   - Index constraints (datetime index, entity identifier)
   - Neutral value (typically 0)
   - Allow NaN policy

2. **Integration Setup**
   - Data pipeline connection (source dataset)
   - Refresh schedule
   - PIT accessor configuration

3. **Backtesting Procedure**
   - Backtest configuration template
   - Performance metrics to compute (Sharpe, turnover, etc.)
   - Benchmark comparison settings

### 15.3 Signal vs Dataset

```
Dataset (General)                   Signal (Specialized Dataset)
─────────────────                   ────────────────────────────
Any schema                          Signal schema (value, datetime, entity)
Any value range                     Bounded range (e.g., [-1, 1])
Optional schedule                   Required schedule
No backtest hooks                   Backtesting procedure attached
In Dataset Inventory                In Signal Hub (subset view)
```

---

## 16) Backtest Architecture

### 16.1 Backtest as Resource

A **BacktestInstance** is a governed resource containing backtest configuration. Unlike other instances, it does not reference a definition because the backtest procedure is fixed code — only the configuration varies.

```
BacktestInstance (Resource)
├── type: "BacktestInstance"
├── parent_id: Project
├── config:
│   ├── assets: ["ES1", "NQ1", "CL1", ...]
│   ├── signals: [signal_resource_id_1, signal_resource_id_2, ...]
│   ├── portfolio_optimizer: optimizer_instance_id (optional)
│   ├── date_range: {start: "2020-01-01", end: "2025-12-31", warmup: 252}
│   ├── rebalance_frequency: "daily" | "weekly" | "monthly"
│   ├── model_retrain_frequency: "weekly" | "monthly" | "quarterly"
│   ├── transaction_costs: {commission: 0.001, slippage: 0.0005}
│   └── constraints: {max_leverage: 1.5, max_position: 0.3}
└── Children:
    └── BacktestRun (execution results)
```

**Benefits of BacktestInstance as Resource:**
- **Shareable**: Promote winning backtest configs from personal → team → system
- **Versionable**: Track configuration changes via ResourceVersion
- **Auditable**: Activity events for all backtest operations
- **RBAC**: Control who can view/run/modify backtests
- **Lineage**: Link to signals, datasets, optimizers used

### 16.2 Backtest Run Outputs

```
BacktestRun (Resource)
├── type: "BacktestRun"
├── parent_id: BacktestInstance
├── status: "running" | "completed" | "failed"
├── outputs:
│   ├── PortfolioWeights (time series dataset)
│   ├── Returns (realized, attributed)
│   ├── Metrics
│   │   ├── Sharpe ratio, Sortino ratio
│   │   ├── Max drawdown, Calmar ratio
│   │   ├── Turnover, Transaction costs
│   │   └── Win rate, Profit factor
│   ├── Trades (execution log)
│   └── Equity curve (time series)
└── Lineage (signal versions, data versions, optimizer version used)
```

---

## 16b) Portfolio Optimization Architecture

### 16b.1 Portfolio Optimizer as Plugin

**PortfolioOptimizerDef** is a plugin definition for portfolio construction algorithms. Different approaches require different code implementations:

| Algorithm | Description | Key Parameters |
|-----------|-------------|----------------|
| `MVOOptimizer` | Mean-Variance Optimization | risk_aversion, target_return |
| `HRPOptimizer` | Hierarchical Risk Parity | linkage_method, distance_metric |
| `BlackLitterman` | Black-Litterman model | tau, confidence_matrix |
| `RiskParity` | Risk parity allocation | risk_budget, risk_measure |
| `RLOptimizer` | Reinforcement Learning | model_architecture, reward_function |

### 16b.2 Portfolio Optimizer Definition Structure

```
PortfolioOptimizerDef/
├── src/
│   ├── __init__.py
│   ├── optimizer.py          # Main optimization logic
│   ├── constraints.py        # Constraint handling
│   └── config.py             # Parameters schema
├── tests/
│   └── test_optimizer.py
└── docs/
    └── README.md
```

### 16b.3 Portfolio Optimizer Instance

```
PortfolioOptimizerInstance (Resource)
├── type: "PortfolioOptimizerInstance"
├── definition_resource_id: PortfolioOptimizerDef
├── definition_version_id: specific version
├── config:
│   ├── constraints:
│   │   ├── max_weight: 0.3
│   │   ├── min_weight: 0.0
│   │   ├── max_leverage: 1.5
│   │   ├── max_turnover: 0.5
│   │   └── sector_limits: {...}
│   ├── risk_model: "exponential_cov" | "shrinkage" | "factor"
│   ├── lookback_window: 252
│   └── algorithm_params: {...}  # Algorithm-specific
└── Children:
    └── PortfolioOptimizationRun (execution results)
```

### 16b.4 Integration with Backtest

BacktestInstance can reference a PortfolioOptimizerInstance:

```python
BacktestInstance(
    assets=["ES1", "NQ1", "CL1"],
    signals=[signal_1_id, signal_2_id],
    portfolio_optimizer=optimizer_instance_id,  # Optional
    date_range={...},
    ...
)
```

If no optimizer is specified, a simple signal-weighted allocation is used.

---

## 17) Definition Hub UI (Extensions Page)

### 17.1 Seven Plugin Types

The Definition Hub (UI name: "Extensions") displays registered plugin definitions in seven categories:

| Plugin Type | Definition Resource | Description |
|-------------|--------------------| -------------|
| **Operator** | `OpDef` | Primitive operations for dataset transformation |
| **Expression Macro** | `OpMacroDef` | Saved DSL expressions as reusable ops |
| **Data Pipeline** | `PipelineDef` | ETL, expression, training, inference pipelines |
| **Data Store** | `StoreDef` | Persistence strategies (Parquet, virtual cache) |
| **Data Accessor** | `AccessorDef` | Retrieval interfaces (PIT, snapshot, field) |
| **ML Model** | `MLModuleDef` | Trainable ops with 5 code components |
| **Portfolio Optimizer** | `PortfolioOptimizerDef` | Portfolio construction algorithms (MVO, HRP, Black-Litterman, Risk-Parity, RL) |

### 17.2 Plugin Definition Package Structure

Each plugin definition is a package containing:

```
PluginDef/
├── src/              # Source code (py files)
│   └── *.py
├── tests/            # Test suites
│   └── test_*.py
└── docs/             # Documentation
    └── README.md
```

### 17.3 Definition → Instance → Execution Pattern

The fundamental lifecycle pattern across all resource types:

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Definition         │     │  Instance           │     │  Execution          │
│  (Plugin/Extension) │────►│  (Configuration)    │────►│  (Run/Action)       │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│  Reusable code      │     │  Config + refs      │     │  Produces versions  │
│  Abstract interface │     │  Concrete usage     │     │  Creates lineage    │
│  Test suite + docs  │     │  In inventory/hub   │     │  Emits activities   │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘

Examples:
PipelineDef       →   DatasetInstance      →   DatasetRun → DatasetVersion
MLModuleDef       →   ModelInstance        →   TrainingRun → ModelVersion
OpDef             →   (used in expression) →   ExpressionRun
```

---

## 18) Instance Hubs Overview

### 18.1 Real Instance Resources by Hub

| Hub | Instance Type | Composed From | Notes |
|-----|---------------|---------------|-------|
| **Dataset Inventory** | DatasetInstance | Pipeline + Store + Accessor + optional Expression | Core data entities |
| **Signal Hub** | SignalInstance | Signal-validated dataset + SignalSpec | Specialized datasets for alpha |
| **MLOps Center** | ModelInstance | MLModuleDef + datasets + config | ML model deployments |
| **Experiment Studio** | ExperimentInstance | Expressions + preview datasets | Research experiments |
| **Backtest Center** | BacktestInstance | Assets + Signals + config (no Def needed) | Backtest configurations |
| **Portfolio Optimizers** | PortfolioOptimizerInstance | PortfolioOptimizerDef + constraints | Allocation algorithms |

### 18.2 Dataset Inventory Composition

A DatasetInstance in Dataset Inventory is composed of:

```
DatasetInstance
├── PipelineInstance (required)
│   └── References: PipelineDef + config
├── StoreInstance (required)
│   └── References: StoreDef + config
├── AccessorInstance (required)
│   └── References: AccessorDef + config
└── ExpressionPipelineInstance (optional)
    └── Uses: Ops, Expression Macros, or ML Models
```

---

## 19) Notes about "memorization"

This file is intended to be uploaded later to restore full context of the system design and governance model.
