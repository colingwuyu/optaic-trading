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

- `PipelineDef` — ETL, Expression pipeline, Training pipeline, Inference pipeline, Monitoring pipeline
- `StoreDef` — Parquet vintage store, partition strategies, virtual cache store
- `AccessorDef` — PIT accessor, snapshot accessor, latest accessor, API accessor
- `OpDef` — primitive ops
- `OpMacroDef` — saved DSL expression as op macro
- `MLModuleDef` — model module (trainer, inference wrapper, metrics evaluator)
- `HookDef` — pre/post hooks for policy, QA gates, notifications

All definitions:
- implement required abstract interfaces
- contain test suite
- are admitted only after evaluation

### 3.2 Instance resources (config-as-code)

Concrete configurations referencing definitions:

- `DatasetInstance` — composed of:
  - `PipelineInstance`
  - `StoreInstance`
  - `AccessorInstance`
  - optionally `ExpressionPipelineInstance` embedded in pipeline
- `TrainingInstance`, `InferenceInstance`, `MonitoringInstance`
- `SignalSpec` resources (range, clipping, neutral value, sampling/availability)
- `ExperimentInstance` with tabs/expressions and preview datasets

Instances are config-as-code on top of defs + versions:
- `(def_resource_id, def_version_id)` + `config_json`

### 3.3 Runs and immutable versions (provenance backbone)

Executions are first-class:

- `Run` (pipeline)
- `TrainingRun`, `InferenceRun`, `MonitoringRun`
- outputs:
  - `DatasetVersion`
  - `ModelVersion`
- provenance:
  - `LineageEdge` linking upstream versions → downstream version

Invariant:
> Only Runs create Versions; Versions create Lineage.

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

### 6.1 Core Concepts

| Concept | Description |
|---------|-------------|
| **ContractRef** | Identifies a contract kind (e.g., `signal.bounds`, `dataset.schema`) and carries its JSON Schema. |
| **ContractInstance** | A concrete configuration for a contract kind + a deterministic `contract_hash`. |
| **ContractBundle** | A set of ContractInstances attached to a resource (the "active bundle"). |
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

### 7.1 Workflow orchestration / DAG execution

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

### 7.2 ML tracking + registry

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

### 7.3 Monitoring and data quality

Lightweight, Windows-friendly options (can be embedded):

- **Data validation**: Pandera (schema checks), optionally Great Expectations for richer suites.
- **Drift/performance monitoring**: Evidently (batch drift reports), WhyLogs (profiling), plus simple custom rules.
- Integrate monitoring as pipelines:
  - monitoring pipelines emit MetricEvents and AlertEvents (as activities)

### 7.4 Data processing and storage

- **Primary file format**: Parquet (vintage partitions)
- **Local analytics**: DuckDB embedded for fast local PIT queries and research notebooks
- **Stores**: implement StoreDef with:
  - ParquetStore (partitioned by date/vintage)
  - VirtualStore (compute-on-read cache)
- **Accessors**: PITAccessor, SnapshotAccessor, LatestAccessor

### 7.5 Scheduling

- Prefer Prefect schedules in orchestrated mode.
- In minimal embedded mode without Prefect:
  - APScheduler for cron-like schedules (dataset refresh / monitoring)
  - schedule metadata stored on DatasetInstance

### 7.6 Plugin system and extension admission

- Plugin loading: `importlib.metadata` entry points + a thin registry layer
- Hook system: `pluggy` pattern or internal hooks
- Evaluation harness:
  - `pytest` for tests
  - static checks: ruff
- Admission workflow:
  - DefinitionSubmission resource + EvaluationRun pipeline
  - owner/delegator approvals for merge to official

### 7.7 Realtime notifications + messaging

- Continue using Centrifugo for realtime channels (chat, activity feeds), managed by optaic supervisor.
- Redis stays optional (e.g., for scaling / Centrifugo redis engine), default off.

### 7.8 Packaging and upgrades (survive `pip upgrade`)

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

## 14) Notes about "memorization"

This file is intended to be uploaded later to restore full context of the system design and governance model.
