# OptAIC Integration Plan: optaic-v0 → optaic-trading

## Overview

**Goal**: Integrate optaic-v0 domain logic (quant trading features) into optaic-trading infrastructure (governance, resources, activities).

**Architecture Insight**:
- optaic-trading = Infrastructure layer (Resource model, Activity emission, RBAC, versioning, real-time)
- optaic-v0 = Domain logic layer (DataAPI, pipelines, expressions, operators, signals, backtests)
- Result = Unified platform with domain logic planted onto governance infrastructure

**Target**: Windows desktop/server deployment, wheel packaging with `pip install optaic` delivering infra + SDK + GUI.

---

## Phase 1: Database Schema & Core Models

**Objective**: Extend optaic-trading's Resource model to support quant domain concepts.

### 1.1 Existing Resource Types (already in optaic-trading)
| Resource Type | Purpose | Notes |
|--------------|---------|-------|
| `Space` | Top-level container | space_kind: personal/team/system |
| `Project` | Work container | Parent: Space |
| `Channel` | Chat/messaging | For collaboration |
| `Run` | Generic execution record | Base for all runs |
| `TrainingRun` | ML training execution | Extends Run |

### 1.2 New Definition Resources (Plugin/Extension Types)
| Resource Type | Purpose | Parent | Notes |
|--------------|---------|--------|-------|
| `PipelineDef` | Data pipeline plugin | Space | ETL code (FRED, Bloomberg, Expression) |
| `StoreDef` | Storage backend plugin | Space | Parquet, SQLite, Virtual stores |
| `AccessorDef` | Data accessor plugin | Space | Simple, PIT, Field accessors |
| `OpDef` | Operator definition | Space | REF, DELTA, MEAN, CORR, etc. |
| `OpMacroDef` | Saved expression/macro | Space/Project | User-defined expressions |
| `MLModuleDef` | ML model definition | Space | Training/inference code |
| `PortfolioOptimizerDef` | Portfolio optimization plugin | Space | MVO, HRP, Black-Litterman, RiskParity, RL |

### 1.3 New Instance Resources (Configured + Executable)
| Resource Type | Purpose | Parent | Definition Ref |
|--------------|---------|--------|----------------|
| `DatasetInstance` | Configured dataset | Project | PipelineDef + StoreDef + AccessorDef |
| `SignalInstance` | Dataset promoted to signal | Project | Inherits from DatasetInstance |
| `ExperimentInstance` | Expression experiment | Project | OpDef/OpMacroDef |
| `ModelInstance` | ML model instance | Project | MLModuleDef |
| `PortfolioOptimizerInstance` | Configured optimizer | Project | PortfolioOptimizerDef |
| `BacktestInstance` | Backtest configuration | Project | None (fixed procedure) |

### 1.4 New Run Resources (Execution Results)
| Resource Type | Purpose | Parent | Notes |
|--------------|---------|--------|-------|
| `PipelineRun` | Pipeline execution | DatasetInstance | Refresh results |
| `ExperimentRun` | Expression evaluation | ExperimentInstance | Preview results |
| `BacktestRun` | Backtest execution | BacktestInstance | PnL, Sharpe, trades |
| `PortfolioOptimizationRun` | Optimization execution | PortfolioOptimizerInstance | Weights, metrics |
| `TrainingRun` | Model training | ModelInstance | (already exists) |
| `InferenceRun` | Model inference | ModelInstance | Predictions |
| `MonitoringRun` | Data & model monitoring | ModelInstance | Drift detection, performance metrics |

### 1.5 New Extension Tables
Create migration: `libs/db/migrations/versions/xxx_quant_domain_tables.py`

```
# Definition extension tables
op_definitions (resource_id FK, category, signature_json, code_ref, parameters_schema_json)
pipeline_definitions (resource_id FK, category, code_ref, parameters_schema_json)
store_definitions (resource_id FK, backend_type, code_ref)
accessor_definitions (resource_id FK, accessor_type, code_ref)
ml_module_definitions (resource_id FK, module_type, code_ref, parameters_schema_json)
portfolio_optimizer_definitions (resource_id FK, algorithm_type, code_ref, parameters_schema_json)

# Instance extension tables
pipeline_instances (resource_id FK, definition_resource_id, config_json, schedule_json, status)
store_instances (resource_id FK, definition_resource_id, config_json, physical_path)
accessor_instances (resource_id FK, definition_resource_id, config_json)
dataset_instances (resource_id FK, pipeline_instance_id, store_instance_id, accessor_instance_id, freshness_status, last_data_date)
signal_specs (resource_id FK, min_value, max_value, allow_nan, neutral_value, index_schema_json)
experiment_instances (resource_id FK, expression_text, input_datasets_json)
model_instances (resource_id FK, definition_resource_id, config_json, artifact_path)
portfolio_optimizer_instances (resource_id FK, definition_resource_id, constraints_json, config_json)
backtest_instances (resource_id FK, assets_json, signals_json, date_range_json, config_json)

# Run extension tables (results)
backtest_runs (resource_id FK, backtest_instance_id, metrics_json, trades_json, equity_curve_ref)
portfolio_optimization_runs (resource_id FK, optimizer_instance_id, weights_json, optimization_metrics_json)
inference_runs (resource_id FK, model_instance_id, predictions_ref, metrics_json)

# Lineage
dataset_lineage (tenant_id, upstream_resource_id, downstream_resource_id, edge_kind)
```

### Files to Create/Modify
- `libs/db/models/quant.py` - New domain models
- `libs/db/migrations/versions/xxx_quant_domain_tables.py` - Migration
- `libs/db/models/__init__.py` - Export new models

---

## Phase 2: Data Platform Core (Port from optaic-v0)

**Objective**: Adapt optaic-v0's DataAPI for the Resource model.

### 2.1 Create libs/data/ Package
Port and adapt from `optaic-v0/dev_tools/src/data/`:

```
libs/data/
├── __init__.py
├── api.py              # DataAPI adapted for Resource model
├── catalog.py          # DatasetInfo, BackendType, DatasetKind
├── registry.py         # PIPELINE_FACTORY, ACCESSOR_FACTORY, STORE_FACTORY
├── expression.py       # Expression engine (from function/expression.py)
├── ops.py              # Operators registry (from function/ops.py)
├── store/
│   ├── base.py         # BaseStore ABC
│   ├── parquet.py      # ParquetStore
│   ├── sqlite.py       # SQLiteStore
│   └── virtual.py      # VirtualStore
├── access/
│   ├── base.py         # BaseAccessor, BaseRequest
│   ├── simple.py       # SimpleAccessor
│   └── pit.py          # PITAccessor (point-in-time)
└── pipelines/
    ├── expression.py   # ExpressionPipeline
    └── etl/            # FRED, Bloomberg, SQLite pipelines
```

### 2.2 Key Adaptation: DataAPI → Resource Model
Replace name-based catalog lookup with Resource ID lookup:
- `get_dataset_info(name)` → `get_dataset_info(resource_id: UUID)`
- Governance: Use RBAC instead of `check_permission()`
- Audit: Use ActivityEnvelope instead of `audit_operation()`

### Source Files to Port
- `optaic-v0/dev_tools/src/data/api.py` → `libs/data/api.py`
- `optaic-v0/dev_tools/src/data/catalog.py` → `libs/data/catalog.py`
- `optaic-v0/dev_tools/src/data/registry.py` → `libs/data/registry.py`
- `optaic-v0/dev_tools/src/function/expression.py` → `libs/data/expression.py`
- `optaic-v0/dev_tools/src/function/ops.py` → `libs/data/ops.py`
- `optaic-v0/dev_tools/src/data/store/*` → `libs/data/store/`
- `optaic-v0/dev_tools/src/data/access/*` → `libs/data/access/`
- `optaic-v0/dev_tools/src/pipelines/*` → `libs/data/pipelines/`

---

## Phase 2.5: Integration Bridge - code_ref Linkage

**Objective**: Clarify how Phase 1 (DB models with `code_ref`) connects to Phase 2 (libs/data/ factories) through the service layer.

### 2.5.1 The Linkage Problem

Phase 1 creates Definition tables with `code_ref` fields:
```python
# libs/db/models/quant.py
class PipelineDefinition(Base):
    code_ref: Mapped[Optional[str]]  # e.g., "ExpressionPipeline" or "FREDPipeline"
    ...
```

Phase 2 creates factories with registered implementations:
```python
# libs/data/registry.py
@register_pipeline("ExpressionPipeline")
class ExpressionPipeline(BasePipeline):
    ...
```

**The Gap**: How does a service know to call `PIPELINE_FACTORY.build("ExpressionPipeline", ...)` when a user wants to execute a DatasetInstance?

### 2.5.2 The Integration Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                 │
│                     (apps/api/services/)                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│ DatasetService │          │ SignalService │          │ OpService     │
└───────────────┘          └───────────────┘          └───────────────┘
        │                           │                           │
        │ 1. Load Resource          │                           │
        │ 2. Load Extension table   │                           │
        │ 3. Get Definition.code_ref│                           │
        │ 4. Factory.build(code_ref)│                           │
        ▼                           ▼                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        PHASE 1: DB MODELS                           │
│                     (libs/db/models/quant.py)                       │
├─────────────────────────────────────────────────────────────────────┤
│  PipelineDefinition.code_ref ─┐                                     │
│  StoreDefinition.code_ref ────┼─► "ExpressionPipeline"              │
│  AccessorDefinition.code_ref ─┘   "ParquetStore"                    │
│                                   "PITAccessor"                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        PHASE 2: FACTORIES                           │
│                     (libs/data/registry.py)                         │
├─────────────────────────────────────────────────────────────────────┤
│  PIPELINE_FACTORY["ExpressionPipeline"] → ExpressionPipeline class  │
│  STORE_FACTORY["ParquetStore"] → ParquetStore class                 │
│  ACCESSOR_FACTORY["PITAccessor"] → PITAccessor class                │
│  OPS_REGISTRY["MEAN"] → mean_op function                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        EXECUTION LAYER                              │
│                     (instantiated objects)                          │
├─────────────────────────────────────────────────────────────────────┤
│  pipeline = PIPELINE_FACTORY.build("ExpressionPipeline", config)    │
│  store = STORE_FACTORY.build("ParquetStore", config)                │
│  accessor = ACCESSOR_FACTORY.build("PITAccessor", config)           │
│  result = pipeline.run(accessor.get(store.read()))                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.5.3 Service Implementation Pattern

```python
# apps/api/services/dataset_service.py
from uuid import UUID
from libs.data.registry import PIPELINE_FACTORY, STORE_FACTORY, ACCESSOR_FACTORY
from libs.db.models.quant import (
    DatasetInstance, PipelineInstance, StoreInstance, AccessorInstance,
    PipelineDefinition, StoreDefinition, AccessorDefinition
)

class DatasetService:
    async def execute_dataset(
        self, session, actor, dataset_id: UUID, *, as_of_date=None
    ):
        """Execute a dataset and return data."""

        # 1. Load the DatasetInstance resource + extension
        dataset_instance = await session.get(DatasetInstance, dataset_id)

        # 2. Load component instances
        pipeline_inst = await session.get(PipelineInstance, dataset_instance.pipeline_instance_id)
        store_inst = await session.get(StoreInstance, dataset_instance.store_instance_id)
        accessor_inst = await session.get(AccessorInstance, dataset_instance.accessor_instance_id)

        # 3. Load component definitions (to get code_ref)
        pipeline_def = await session.get(PipelineDefinition, pipeline_inst.definition_resource_id)
        store_def = await session.get(StoreDefinition, store_inst.definition_resource_id)
        accessor_def = await session.get(AccessorDefinition, accessor_inst.definition_resource_id)

        # 4. Build execution objects from factories using code_ref
        pipeline = PIPELINE_FACTORY.build(
            pipeline_def.code_ref,          # e.g., "ExpressionPipeline"
            resource_id=pipeline_inst.resource_id,
            config=pipeline_inst.config_json,
        )
        store = STORE_FACTORY.build(
            store_def.code_ref,             # e.g., "ParquetStore"
            resource_id=store_inst.resource_id,
            config=store_inst.config_json,
            data_dir=self.data_dir,
        )
        accessor = ACCESSOR_FACTORY.build(
            accessor_def.code_ref,          # e.g., "PITAccessor"
            resource_id=accessor_inst.resource_id,
            config=accessor_inst.config_json,
            store=store,
        )

        # 5. Execute
        df = accessor.get(as_of_date=as_of_date)
        return df
```

### 2.5.4 Seeding Built-in Definitions

System-provided definitions (built-in pipelines, stores, accessors, ops) must be seeded into the database at startup or migration time:

```python
# scripts/seed_definitions.py
BUILT_IN_PIPELINES = [
    {"name": "ExpressionPipeline", "code_ref": "ExpressionPipeline", "category": "expression"},
    {"name": "FREDPipeline", "code_ref": "FREDPipeline", "category": "etl"},
]

BUILT_IN_STORES = [
    {"name": "ParquetStore", "code_ref": "ParquetStore", "backend_type": "parquet"},
    {"name": "VirtualStore", "code_ref": "VirtualStore", "backend_type": "virtual"},
]

BUILT_IN_ACCESSORS = [
    {"name": "SimpleAccessor", "code_ref": "SimpleAccessor", "accessor_type": "simple"},
    {"name": "PITAccessor", "code_ref": "PITAccessor", "accessor_type": "pit"},
]

BUILT_IN_OPS = [
    {"name": "MEAN", "code_ref": "MEAN", "category": "rolling"},
    {"name": "REF", "code_ref": "REF", "category": "time_series"},
    {"name": "DELTA", "code_ref": "DELTA", "category": "time_series"},
    # ... all ops from OPS_REGISTRY
]

async def seed_definitions(session, system_space_id):
    """Seed built-in definitions into the system space."""
    for pipeline in BUILT_IN_PIPELINES:
        resource = Resource(
            tenant_id=SYSTEM_TENANT,
            type="PipelineDef",
            parent_id=system_space_id,
            name=pipeline["name"],
            space_kind="system",
        )
        session.add(resource)

        definition = PipelineDefinition(
            resource_id=resource.id,
            tenant_id=SYSTEM_TENANT,
            category=pipeline["category"],
            code_ref=pipeline["code_ref"],
            interface_spec="optaic.interfaces.BasePipeline",
        )
        session.add(definition)
```

### 2.5.5 Key Insight: Two-Table Pattern

Every quant resource uses a **two-table pattern**:

1. **Resource table**: Standard governance (RBAC, versioning, activity, hierarchy)
2. **Extension table**: Domain-specific data (code_ref, config, metrics)

```
┌─────────────────┐     ┌─────────────────────────┐
│    resources    │ 1─1 │  pipeline_definitions   │
├─────────────────┤     ├─────────────────────────┤
│ id (PK)         │◄────│ resource_id (PK, FK)    │
│ tenant_id       │     │ tenant_id               │
│ type            │     │ category                │
│ parent_id       │     │ code_ref                │ ← Links to Factory
│ name            │     │ interface_spec          │
│ metadata_json   │     │ guardrail_contracts     │
└─────────────────┘     └─────────────────────────┘
```

This pattern enables:
- **Governance**: RBAC, audit, versioning via Resource table
- **Domain Logic**: code_ref execution via Extension table
- **Composition**: DatasetInstance references Pipeline/Store/Accessor Instances

### 2.5.6 Files to Create/Modify

| File | Purpose |
|------|---------|
| `scripts/seed_definitions.py` | Seed built-in definitions at startup |
| `apps/api/services/dataset_service.py` | Bridge Resources → Factories |
| `libs/data/registry.py` | Ensure all code_refs are registered |
| `libs/core/startup.py` | Call seed_definitions on first boot |

---

## Phase 3: Service Layer with Activity Emission

**Objective**: Create domain services following optaic-trading patterns.

### 3.1 Services to Create
```
apps/api/services/
├── dataset_service.py    # CRUD, refresh, preview
├── signal_service.py     # Register, validate, promote
├── pipeline_service.py   # Submit, configure, execute
├── op_service.py         # List operators, evaluate expressions
└── mlops_service.py      # Model lifecycle
```

### 3.2 Service Pattern (from resources.py:29-102)
```python
class DatasetService:
    async def create_dataset_instance(
        self, session, actor, payload, guardrails
    ) -> Resource:
        # 1. Authorize: authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)
        # 2. Guardrails: guardrails.validate_at_gate(...)
        # 3. Domain function: Create Resource + DatasetInstance
        # 4. Activity: tx_activity(db, envelope, domain_fn)
        pass
```

### Activity Actions to Implement
- `dataset.created`, `dataset.updated`, `dataset.deleted`
- `dataset.refresh_started`, `dataset.refresh_completed`, `dataset.refresh_failed`
- `signal.registered`, `signal.validated`, `signal.promoted`
- `expression.evaluated`, `expression.saved`
- `pipeline.submitted`, `pipeline.deployed`

---

## Phase 4: API Routers

**Objective**: Create REST endpoints for quant domain.

### 4.1 New Routers
```
apps/api/routers/
├── datasets.py       # /datasets
├── signals.py        # /signals
├── pipelines.py      # /pipelines
├── ops.py            # /ops
├── experiments.py    # /experiments
└── mlops.py          # /mlops
```

### 4.2 Router Pattern (from resources.py)
- `@router.post("")` → Create with guardrails + activity
- `@router.get("/{id}")` → Read with RBAC
- `@router.get("/{id}/status")` → Status check
- `@router.post("/{id}/refresh")` → Trigger action

### Key Endpoints
```
POST   /datasets                    # Create dataset instance
GET    /datasets/{id}               # Get dataset info
GET    /datasets/{id}/status        # Get freshness status
GET    /datasets/{id}/preview       # Preview data (PIT-aware)
POST   /datasets/{id}/refresh       # Trigger refresh

POST   /signals                     # Register as signal
GET    /signals/{id}                # Get signal spec
POST   /signals/{id}/validate       # Validate against spec

GET    /ops                         # List operators
POST   /ops/evaluate                # Execute expression

POST   /experiments                 # Create experiment
GET    /experiments/{id}            # Get experiment
POST   /experiments/{id}/run        # Run expression
```

### Files to Create
- `apps/api/routers/datasets.py`
- `apps/api/routers/signals.py`
- `apps/api/routers/pipelines.py`
- `apps/api/routers/ops.py`
- `apps/api/routers/experiments.py`
- `apps/api/schemas/quant.py` - Pydantic DTOs
- `apps/api/main.py` - Register routers

---

## Phase 5: SDK Extensions

**Objective**: Extend Python SDK with quant domain clients.

### 5.1 New SDK Modules
```
libs/sdk_py/
├── datasets.py       # DatasetsClient
├── signals.py        # SignalsClient
├── pipelines.py      # PipelinesClient
├── ops.py            # OpsClient
└── experiments.py    # ExperimentsClient
```

### 5.2 Client Pattern
```python
class DatasetsClient:
    async def list(self, *, parent_id=None, status=None, tags=None) -> list[dict]
    async def create(self, name, pipeline_def, pipeline_config, ...) -> dict
    async def get(self, dataset_id) -> dict
    async def preview(self, dataset_id, *, start_date=None, end_date=None, as_of_date=None) -> dict
    async def refresh(self, dataset_id) -> dict
```

### 5.3 Extend Main Client
```python
# libs/sdk_py/client.py
class AsyncPlatformClient:
    def __init__(self, ...):
        # Existing...
        self.datasets = DatasetsClient(self)
        self.signals = SignalsClient(self)
        self.ops = OpsClient(self)
```

### Files to Create/Modify
- `libs/sdk_py/datasets.py` (new)
- `libs/sdk_py/signals.py` (new)
- `libs/sdk_py/ops.py` (new)
- `libs/sdk_py/client.py` (extend)
- `libs/sdk_ts/` - TypeScript equivalents

---

## Phase 6: UI Migration

**Objective**: Replace apps/web/ with optaic-v0 Next.js UI.

**CORRECT Source**: `optaic-v0/dev_tools/src/ui/next_app/` (Next.js 14 SPA)
- NOT `optaic-v0/OPTAIC-UI/` (old/legacy version)

### 6.1 UI Architecture (from optaic-v0)
```
optaic-v0/dev_tools/src/ui/
├── server.py                 # FastAPI backend server
├── api.py                    # Main data API (3,834 lines)
├── auth_router.py            # Authentication
├── governance_api.py         # Resource governance
├── next_app/                 # PRIMARY FRONTEND (Next.js 14)
│   ├── src/
│   │   ├── app/              # Next.js App Router pages
│   │   ├── components/       # 79 React TSX components
│   │   ├── context/          # 8 React context providers
│   │   ├── services/         # API clients (sdk.ts, dataService.ts)
│   │   ├── types/            # TypeScript interfaces
│   │   └── hooks/            # Custom React hooks
│   ├── package.json          # Dependencies
│   └── tsconfig.json
```

### 6.2 Migration Strategy
1. Backup `apps/web/` → `apps/web.bak/`
2. Copy `optaic-v0/dev_tools/src/ui/next_app/` → `apps/web/`
3. Update `apps/web/src/services/sdk.ts` to call optaic-trading API endpoints
4. Replace mock data services with real API calls
5. Integrate with existing Centrifugo for real-time updates

### 6.3 API Service Updates
```typescript
// apps/web/src/services/api.ts
const API_BASE = '/api';

export const api = {
  datasets: {
    list: () => fetch(`${API_BASE}/datasets`),
    get: (id) => fetch(`${API_BASE}/datasets/${id}`),
    preview: (id, opts) => fetch(`${API_BASE}/datasets/${id}/preview?${params(opts)}`),
    refresh: (id) => fetch(`${API_BASE}/datasets/${id}/refresh`, {method: 'POST'}),
  },
  ops: {
    list: () => fetch(`${API_BASE}/ops`),
    evaluate: (expr) => fetch(`${API_BASE}/ops/evaluate`, {method: 'POST', body: expr}),
  },
  signals: {
    list: () => fetch(`${API_BASE}/signals`),
    register: (data) => fetch(`${API_BASE}/signals`, {method: 'POST', body: data}),
  },
}
```

### 6.4 Context Providers to Adapt
| Context | Source File | Integration |
|---------|-------------|-------------|
| `AuthContext` | `context/AuthContext.tsx` | Connect to `/api/auth` |
| `DashboardContext` | `context/DashboardContext.tsx` | Connect to `/api/datasets`, `/api/resources` |
| `SDKContext` | `context/SDKContext.tsx` | Replace mock with real SDK client |
| `BacktestContext` | `context/BacktestContext.tsx` | Connect to `/api/backtests` |
| `SignalHubContext` | `context/SignalHubContext.tsx` | Connect to `/api/signals` |

### 6.5 Real-time Integration
Connect UI components to existing Centrifugo channels:
- `dataset:{id}:status` - Dataset freshness updates
- `run:{id}:progress` - Pipeline run progress
- `activity` - Global activity feed

### 6.6 Key Pages to Connect
| Page | Route | API Endpoints |
|------|-------|---------------|
| Experiment Studio | `/` | `/ops`, `/datasets/preview` |
| Data Inventory | `/inventory` | `/datasets`, `/resources` |
| Definition Hub | `/catalog` | `/pipelines`, `/ops` |
| Signal Hub | `/signal-hub` | `/signals` |
| Backtests | `/backtest` | `/backtests`, `/runs` |
| Live Monitor | `/monitor` | `/datasets/status`, `/runs` |
| MLOps Center | `/mlops` | `/mlops`, `/models` |

### 6.7 Key Components (79 TSX files)
| Component | Purpose |
|-----------|---------|
| `ExperimentStudio.tsx` | Expression editor + preview |
| `SignalHubView.tsx` | Signal management |
| `DatasetTree.tsx` | Dataset catalog browser |
| `BacktestConfigModal.tsx` | Backtest configuration |
| `AssetChart.tsx` | Candlestick/line charts |
| `LineageGraph.tsx` | Data lineage visualization |
| `CodeEditor.tsx` | Monaco-based code editor |

---

## Phase 0: Skills Preparation (BEFORE Implementation)

**Objective**: Create/enhance design pattern skills BEFORE starting implementation to ensure consistent guidance.

### 0.1 New Skills to Create

#### `optaic-v0-migration` Skill
```
.claude/skills/optaic-v0-migration/
├── SKILL.md
└── references/
    ├── mapping.md              # optaic-v0 → optaic-trading mappings
    ├── adaptation-rules.md     # How to adapt code patterns
    └── examples/
        ├── dataapi_before.py   # Original optaic-v0 code
        └── dataapi_after.py    # Adapted for optaic-trading
```

**Content:**
- Map optaic-v0 patterns to optaic-trading patterns
- `check_permission()` → RBAC authorization
- `audit_operation()` → ActivityEnvelope emission
- Name-based catalog → Resource ID lookup
- Governance hooks → Guardrails engine

#### `definition-resource-design` Skill
```
.claude/skills/definition-resource-design/
├── SKILL.md
└── references/
    ├── structure.md            # Definition resource structure
    ├── contracts.md            # How to define guardrail contracts
    ├── compatibility.md        # Upstream/downstream rules
    └── examples/
        └── pipeline_def.py     # Example PipelineDef
```

**Content:**
- How to design `interface_spec`, `input_schema`, `output_schema`
- How to define `compatibility_rules` for upstream/downstream
- How to embed `guardrail_contracts` (the "law")
- Definition → Instance → Run lifecycle

#### `instance-resource-design` Skill
```
.claude/skills/instance-resource-design/
├── SKILL.md
└── references/
    ├── structure.md            # Instance resource structure
    ├── config-patterns.md      # Config JSON patterns
    ├── definition-refs.md      # How to reference definitions
    └── examples/
        └── dataset_instance.py # Example DatasetInstance
```

**Content:**
- How to reference Definition resources (`definition_resource_id`, `definition_version_id`)
- Config patterns (`config_json`, `schedule_json`)
- Composition patterns (Pipeline + Store + Accessor → Dataset)
- Special cases (BacktestInstance with no definition)

#### `run-resource-design` Skill
```
.claude/skills/run-resource-design/
├── SKILL.md
└── references/
    ├── structure.md            # Run resource structure
    ├── execution-tracking.md   # Status, metrics, outputs
    ├── lineage.md              # How to track lineage
    └── examples/
        └── backtest_run.py     # Example BacktestRun
```

**Content:**
- Run resource structure (parent Instance, status, outputs)
- Execution tracking (started_at, completed_at, metrics_json)
- Output artifacts (equity_curve_ref, weights_json, etc.)
- Lineage tracking (which versions of upstream resources were used)

### 0.2 Existing Skills to Update

| Skill | Updates Needed |
|-------|----------------|
| `quant-resource-patterns` | Add BacktestInstance, PortfolioOptimizerDef/Instance, MonitoringRun |
| `guardrails-contracts` | Add "Law vs Police" architecture, Definition-embedded contracts |
| `activity-logging` | Add new activity actions (backtest.*, optimizer.*, monitoring.*) |

### 0.3 Skills Reference in Blueprint

Ensure each skill references the relevant blueprint sections:
- `definition-resource-design` → Blueprint Section 3.1, 6.0
- `instance-resource-design` → Blueprint Section 3.2, 16, 16b
- `run-resource-design` → Blueprint Section 3.3
- `guardrails-contracts` → Blueprint Section 6

---

## Phase 6b: Future Plugin Development Skills

**Objective**: Create skills for external developers AFTER system interfaces are finalized.

### 6b.1 Plugin Skills (Create in Phase 9)

After the system is complete, create skills for quant researchers and data teams:

| Skill | Target Users | Purpose |
|-------|--------------|---------|
| `store-implementer` | Data engineers | Guide new StoreDef plugin development |
| `accessor-implementer` | Data engineers | Guide new AccessorDef plugin development |
| `pipeline-implementer` | Data engineers | Guide new PipelineDef plugin development |
| `op-implementer` | Quant researchers | Guide new OpDef plugin development |
| `optimizer-implementer` | Quant researchers | Guide new PortfolioOptimizerDef development |
| `ml-module-implementer` | ML engineers | Guide new MLModuleDef development |

### 6b.2 Plugin Skill Structure

```
.claude/skills/store-implementer/           # For data engineers
├── SKILL.md                                # How to create new StoreDef
└── references/
    ├── interface.md                        # BaseStore interface docs
    ├── patterns.md                         # Required patterns
    ├── contracts.md                        # What guardrail contracts to include
    └── examples/
        ├── parquet_store.py                # Reference implementation
        └── sqlite_store.py                 # Another example
```

### 6b.3 Abstract Interfaces (Define During Phase 2)

Create interfaces in `libs/data/interfaces/` that plugin skills will reference:

```python
# libs/data/interfaces/store.py
class BaseStore(ABC):
    @abstractmethod
    def write(self, data: pd.DataFrame, partition_key: str) -> None: ...
    @abstractmethod
    def read(self, partition_key: str) -> pd.DataFrame: ...

# libs/data/interfaces/pipeline.py
class BasePipeline(ABC):
    @abstractmethod
    def run(self, config: dict, as_of_date: date) -> PipelineResult: ...

# libs/data/interfaces/optimizer.py
class BasePortfolioOptimizer(ABC):
    @abstractmethod
    def optimize(self, signals: pd.DataFrame, constraints: Constraints) -> pd.Series: ...
```

These interfaces are the "law" that plugin skills will teach external developers to follow.

---

## Phase 7: Guardrails Architecture

**Objective**: Implement the guardrails system as the "police" that enforces contracts defined in Definition Resources.

### 7.1 Architecture: Law vs Police

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DEFINITION RESOURCES (The Law)                    │
├─────────────────────────────────────────────────────────────────────┤
│  PipelineDef / StoreDef / AccessorDef / OpDef / PortfolioOptimizerDef│
│  ├── interface_spec        # Abstract interface to implement         │
│  ├── input_schema          # Expected input types/formats            │
│  ├── output_schema         # Expected output types/formats           │
│  ├── compatibility_rules   # What upstream/downstream can connect    │
│  └── guardrail_contracts   # Validation rules to enforce             │
│      ├── signal.bounds: {min: -1, max: 1}                           │
│      ├── pit.policy: {knowledge_date_required: true}                │
│      └── dataset.schema: {columns: [...]}                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    GUARDRAILS ENGINE (The Police)                    │
├─────────────────────────────────────────────────────────────────────┤
│  Reads contracts FROM Definition Resources, enforces them at gates: │
│                                                                      │
│  Gate 1: Instance Creation                                           │
│  ├── Validate config against Definition's guardrail_contracts        │
│  └── Check compatibility_rules for upstream/downstream connections   │
│                                                                      │
│  Gate 2: Run Execution (before)                                      │
│  ├── Validate inputs match Definition's input_schema                 │
│  └── Check all upstream dependencies are ready                       │
│                                                                      │
│  Gate 3: Data Write (real-time)                                      │
│  ├── Validate data against output_schema                             │
│  ├── Enforce signal.bounds, pit.policy, etc.                         │
│  └── Block or warn based on subspace policy (staging=warn, official=block) │
│                                                                      │
│  Gate 4: Promotion/Merge                                             │
│  └── All contracts must pass before promotion to official            │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 Definition Resource Contract Fields

Each Definition Resource carries its validation requirements:

```python
# Example: SignalPipelineDef
class SignalPipelineDef:
    # Interface requirements
    interface_spec = "optaic.interfaces.BasePipeline"

    # Input/Output schemas
    input_schema = {
        "datasets": {"type": "array", "items": {"$ref": "#/DatasetInstance"}},
    }
    output_schema = {
        "type": "DataFrame",
        "columns": ["date", "entity", "value"],
        "value_range": {"min": -1, "max": 1}  # Signal bounds
    }

    # Compatibility rules
    compatibility_rules = {
        "upstream_types": ["DatasetInstance"],
        "downstream_types": ["SignalInstance", "BacktestInstance"]
    }

    # Guardrail contracts (the law)
    guardrail_contracts = [
        {"kind": "signal.bounds", "config": {"min": -1, "max": 1, "allow_nan": False}},
        {"kind": "pit.policy", "config": {"knowledge_date_required": True}},
    ]
```

### 7.3 Guardrails Engine Implementation

```python
# optaic/guardrails/engine.py
class GuardrailsEngine:
    """The Police - enforces contracts from Definitions."""

    async def validate_instance_creation(
        self,
        definition: Resource,          # The Definition being instantiated
        instance_config: dict,          # Proposed instance configuration
        upstream_refs: list[UUID],      # Connected upstream resources
    ) -> ValidationReport:
        """Gate 1: Validate before creating Instance from Definition."""

        # Load contracts from Definition
        contracts = definition.metadata_json.get("guardrail_contracts", [])

        # Check compatibility rules
        compat_rules = definition.metadata_json.get("compatibility_rules", {})
        for upstream_id in upstream_refs:
            upstream = await self.get_resource(upstream_id)
            if upstream.type not in compat_rules.get("upstream_types", []):
                return ValidationReport(ok=False, issues=[
                    Issue(code="INCOMPATIBLE_UPSTREAM", ...)
                ])

        # Validate config against each contract
        for contract_spec in contracts:
            validator = self.get_validator(contract_spec["kind"])
            result = validator.validate_config(instance_config, contract_spec["config"])
            if not result.ok:
                return result

        return ValidationReport(ok=True)

    async def validate_data_write(
        self,
        instance: Resource,             # The Instance writing data
        data: pd.DataFrame,             # Data being written
    ) -> ValidationReport:
        """Gate 3: Validate data before writing to store."""

        # Get Definition from Instance
        definition = await self.get_definition(instance)
        contracts = definition.metadata_json.get("guardrail_contracts", [])

        for contract_spec in contracts:
            validator = self.get_validator(contract_spec["kind"])
            result = validator.validate_data(data, contract_spec["config"])
            if not result.ok:
                # Enforce policy based on subspace
                if instance.subspace_kind == "official":
                    return result  # BLOCK
                else:
                    self.emit_warning(result)  # WARN but continue

        return ValidationReport(ok=True)
```

### 7.4 Contract Validators (Pluggable)

```python
# optaic/guardrails/validators/signal_bounds.py
class SignalBoundsValidator:
    kind = "signal.bounds"

    def validate_data(self, data: pd.DataFrame, config: dict) -> ValidationReport:
        min_val = config.get("min", -1)
        max_val = config.get("max", 1)
        allow_nan = config.get("allow_nan", False)

        issues = []
        if (data["value"] < min_val).any():
            issues.append(Issue(code="BELOW_MIN", ...))
        if (data["value"] > max_val).any():
            issues.append(Issue(code="ABOVE_MAX", ...))
        if not allow_nan and data["value"].isna().any():
            issues.append(Issue(code="CONTAINS_NAN", ...))

        return ValidationReport(ok=len(issues) == 0, issues=issues)

# optaic/guardrails/validators/pit_policy.py
class PITPolicyValidator:
    kind = "pit.policy"

    def validate_data(self, data: pd.DataFrame, config: dict) -> ValidationReport:
        if config.get("knowledge_date_required", True):
            if "knowledge_date" not in data.columns:
                return ValidationReport(ok=False, issues=[
                    Issue(code="MISSING_KNOWLEDGE_DATE", ...)
                ])
        return ValidationReport(ok=True)
```

### 7.5 Key Insight: Contracts Live in Definitions

**Before (old understanding):**
- Guardrails contracts are standalone resources
- Manually attached to instances

**After (your clarification):**
- Definitions contain the "law" (contracts, schemas, compatibility rules)
- Guardrails Engine is the "police" that reads and enforces the law
- Instance creation automatically inherits contracts from its Definition
- No manual attachment needed - it's automatic from the Definition

---

## Phase 8: Packaging & DevOps

**Objective**: Single wheel with full platform.

### 8.1 pyproject.toml Updates
```toml
[project.optional-dependencies]
data = ["pandas>=2.0", "pyarrow>=14.0", "duckdb>=0.9"]
ml = ["scikit-learn>=1.3", "xgboost>=2.0"]
full = ["optaic[data,ml]"]

[project.scripts]
optaic = "optaic.cli:app"
```

### 8.2 CLI Commands
```
optaic server                    # Start API + worker + agent + UI
optaic server --with-prefect     # Include Prefect
optaic upgrade --apply           # Apply migrations
optaic upgrade --dry-run         # Preview changes
optaic demo init                 # Initialize demo data
```

### 8.3 Data Migration Script
```python
# scripts/migrate_v0_to_trading.py
async def migrate_datasets():
    """Migrate optaic-v0 catalog to optaic-trading resources."""
    # 1. Read v0 DATA_CATALOG
    # 2. Create Resource records
    # 3. Create DatasetInstance records
    # 4. Copy physical stores
```

### 8.4 Version Management
- `infra/versions.json` - Track component versions
- `optaic/version.py` - Runtime version
- Artifactory lanes: prod, uat, staging

---

## Implementation Order

```
═══════════════════════════════════════════════════════════════════════
Phase 0: SKILLS PREPARATION (BEFORE Implementation)
═══════════════════════════════════════════════════════════════════════
    │
    ├── 0a: Create/Enhance Design Pattern Skills
    │   ├── optaic-v0-migration        # Guide porting code from optaic-v0
    │   ├── definition-resource-design # How to design Definition resources
    │   ├── instance-resource-design   # How to design Instance resources
    │   └── run-resource-design        # How to design Run resources
    │
    ├── 0b: Update Existing Skills with New Resource Types
    │   ├── quant-resource-patterns    # Add BacktestInstance, PortfolioOptimizerDef/Instance
    │   ├── guardrails-contracts       # Add "Law vs Police" architecture
    │   └── activity-logging           # Add new activity actions
    │
    └── 0c: Document Blueprint Changes
        └── Ensure skills reference updated blueprint sections
    ↓
═══════════════════════════════════════════════════════════════════════
IMPLEMENTATION BEGINS (with skills guidance)
═══════════════════════════════════════════════════════════════════════
    ↓
Phase 1: Database Schema (foundation) ✅ DONE
    │   - libs/db/models/quant.py created
    │   - Migration h1b2c3d4e5f6_quant_domain_tables.py created
    │   [USE: definition-resource-design, instance-resource-design, run-resource-design]
    ↓
Phase 2: Data Platform Core (port optaic-v0 data layer) ✅ DONE
    │   ├── 2a: Define Abstract Interfaces ✅
    │   ├── 2b: Port reference implementations from optaic-v0 ✅
    │   ├── 2c: 225 unit tests passing ✅
    │   └── libs/data/ package complete (stores, accessors, ops, expression engine)
    │   [USE: optaic-v0-migration, data-pipeline-patterns]
    ↓
Phase 2.5: Integration Bridge - code_ref Linkage ← CURRENT
    │   ├── 2.5a: Verify code_ref fields match factory registration keys
    │   ├── 2.5b: Create scripts/seed_definitions.py for built-in defs
    │   └── 2.5c: Wire up service layer to use code_ref → Factory pattern
    │   [USE: quant-resource-patterns, sdk-patterns]
    ↓
Phase 3: Service Layer (activity emission + guardrails)
    │   [USE: activity-logging, guardrails-contracts]
    ↓
Phase 4: API Routers (REST endpoints)
    │   [USE: quant-resource-patterns]
    ↓
Phase 5: SDK Extensions (Python + TypeScript)
    │   [USE: sdk-patterns]
    ↓
Phase 6: UI Migration (replace apps/web/)
    ↓
Phase 7: Guardrails Architecture (enforce Definition contracts)
    ↓
Phase 8: Packaging & DevOps (wheel + deployment)
    ↓
═══════════════════════════════════════════════════════════════════════
SYSTEM COMPLETE - Interfaces Finalized
═══════════════════════════════════════════════════════════════════════
    ↓
Phase 9: Plugin Development Skills (FUTURE)
    ├── Create skills for quant researchers / data teams
    ├── store-implementer, pipeline-implementer, optimizer-implementer
    └── Guide external developers to extend the system
```

**Three Skill Stages:**

| Stage | Skills | Target Users | Purpose |
|-------|--------|--------------|---------|
| **Phase 0** | optaic-v0-migration, definition-resource-design, instance-resource-design, run-resource-design | Development team | Prepare guidance BEFORE implementation |
| **Phase 1-8** | activity-logging, guardrails-contracts, quant-resource-patterns, data-pipeline-patterns, sdk-patterns | Development team | Use during implementation |
| **Phase 9** | store-implementer, pipeline-implementer, optimizer-implementer, ml-module-implementer | Quant researchers, data teams | Guide plugin development (AFTER system built) |

---

## Critical Files Summary

### Phase 1 & 2 (COMPLETE)
- ✅ `libs/db/models/quant.py` - Domain models with code_ref fields
- ✅ `libs/db/migrations/versions/h1b2c3d4e5f6_quant_domain_tables.py` - Migration
- ✅ `libs/db/models/__init__.py` - Exports quant models
- ✅ `libs/data/` - Entire package (stores, accessors, ops, expression engine)
- ✅ `libs/data/tests/` - 225 unit tests passing

### Phase 2.5 (Integration Bridge)
- 🔲 `scripts/seed_definitions.py` - Seed built-in definitions at startup
- 🔲 `libs/core/startup.py` - Call seed_definitions on first boot
- 🔲 Verify code_ref values match factory registration keys

### Modify (Future Phases)
- `libs/sdk_py/client.py` - Add domain clients
- `apps/api/main.py` - Register new routers
- `optaic/cli.py` - Add upgrade/migration commands
- `pyproject.toml` - Dependencies and extras

### Create (Future Phases)
- `apps/api/services/dataset_service.py`
- `apps/api/services/signal_service.py`
- `apps/api/services/op_service.py`
- `apps/api/routers/datasets.py`
- `apps/api/routers/signals.py`
- `apps/api/routers/ops.py`
- `apps/api/routers/experiments.py`
- `apps/api/schemas/quant.py`
- `libs/sdk_py/datasets.py`
- `libs/sdk_py/signals.py`
- `libs/sdk_py/ops.py`
- `optaic/guardrails/contracts/signal_bounds.py`
- `scripts/migrate_v0_to_trading.py`

### Port (optaic-v0 → optaic-trading)
- `dev_tools/src/data/` → `libs/data/`
- `dev_tools/src/function/` → `libs/data/`
- `dev_tools/src/pipelines/` → `libs/data/pipelines/`
- `dev_tools/src/ui/next_app/` → `apps/web/` (Next.js 14 frontend)
- `dev_tools/src/ui/api.py` → Reference for API router patterns

---

## Risk Mitigation

1. **Data Migration**: Create rollback scripts alongside migration
2. **API Breaking Changes**: Version APIs (`/v1/datasets`)
3. **Testing**: Port optaic-v0 tests alongside domain logic
4. **Performance**: Add caching for PIT queries, paginate large datasets
5. **UI Transition**: Feature flags for gradual rollout
