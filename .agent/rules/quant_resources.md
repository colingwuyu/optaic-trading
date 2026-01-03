---
trigger: model_decision
description: Agent trigger: Load this file when implementing quant domain resources like Dataset, Signal, Portfolio, Backtest, or any Definition/Instance/Run resource types.
---

# Quant Resource Patterns

Guide for implementing domain resources in OptAIC's resource-based architecture.

## 1. Three-Tier Resource Model

```
Definition (Plugin)         Instance (Config)              Run (Execution)
-------------------        ------------------             ----------------
BloombergPipelineDef   ->  SPX_OHLCV_Dataset          ->  PipelineRun
PortfolioOptimizerDef  ->  MVO_Conservative           ->  PortfolioOptimizationRun
MLModuleDef            ->  XGBoost_Predictor          ->  TrainingRun, InferenceRun
(none)                 ->  BacktestInstance           ->  BacktestRun
```

## 1a. Flow Execution Resources (CRITICAL)

**Flow Execution Resources are distinct from Runs.**

| Concept | Type | Created When | Example |
|---------|------|--------------|---------|
| Flow Execution Resource | Static | Instance created | Prefect Deployment |
| Run | Dynamic | Flow triggered | Prefect Flow Run |

```
Instance creation:
├── Create Resource + extension table
├── Create Flow Execution Resource(s)   ← Static capability
│   ├── Prefect deployment(s)
│   ├── MLflow experiment (for models)
│   └── EvidentlyAI project (for monitoring)
└── Store handles in Instance extension table

Run trigger:
├── Check upstream freshness (flow-to-flow lineage)
├── Create Run resource record          ← Dynamic activity
├── Submit to orchestrator
└── Track status, metrics, outputs
```

**Key Pattern**: When implementing Instance creation, ALWAYS also create Flow Execution Resources.

## 2. Resource Type Summary

### Definition Resources
PipelineDef, StoreDef, AccessorDef, OpDef, OpMacroDef, MLModuleDef, PortfolioOptimizerDef

### Instance Resources
DatasetInstance, SignalInstance, ExperimentInstance, ModelInstance, PortfolioOptimizerInstance, BacktestInstance

### Run Resources
PipelineRun, ExperimentRun, BacktestRun, PortfolioOptimizationRun, TrainingRun, InferenceRun, MonitoringRun

## 3. Implementation Workflow

1. Determine Resource Tier (Definition/Instance/Run)
2. Create DB Model in `libs/db/models/<domain>.py`
3. Create DTOs in `libs/core/domain/<domain>.py`
4. Create Service Layer in `libs/core/domain/<domain>_service.py`
5. Register ResourceType in `libs/core/resources.py`
6. Generate Migration: `optaic db revision --autogenerate -m "add <domain>"`
7. Write Tests in `libs/core/tests/test_<domain>.py`

## 4. Critical Rules

1. **Lazy imports** - Heavy deps use `TYPE_CHECKING` blocks
2. **Activity emission** - All mutations emit activities in service layer
3. **Guardrails hooks** - Validate at lifecycle gates
4. **Version tracking** - Instances reference definition versions
5. **code_ref linkage** - Services bridge DB models to factories via Definition.code_ref
6. **Flow Execution Pairing** - Instance creation MUST create Flow Execution Resources
7. **Lineage is Flow-to-Flow** - Dependencies track flow statuses, not instance relationships
8. **Status Aggregation** - Instance status aggregates from its Flow(s)
9. **Real-Time Updates** - Flow status changes publish to Centrifugo channels

## 4a. Lineage Checking Before Execution

Before triggering a Run, check upstream freshness:

```python
from libs.orchestration import (
    LineageResolver, FreshnessChecker, UpstreamNotReadyError
)

async def trigger_pipeline_run(session, actor, dataset_id, force=False):
    resolver = LineageResolver()
    checker = FreshnessChecker(status_store)

    # Check upstream freshness
    report = await resolver.check_upstream_freshness(
        session, dataset_id, checker
    )

    if not report.all_ready and not force:
        raise UpstreamNotReadyError(
            f"{len(report.blocking_resources)} upstream(s) not ready",
            blocking_resources=report.blocking_resources,
        )

    # Proceed with Run creation
    ...
```

## 4b. Status Flow

```
Instance.status = aggregate(flow.statuses)

DatasetStatus enum:
├── NOT_INITIALIZED  (no data exists)
├── READY           (current and valid)
├── STALE           (outdated, needs refresh)
├── STALE_SOURCE_DELAYED (source has no new data)
└── ERROR           (pipeline failed)
```

## 5. code_ref Integration

The `code_ref` field in Definition extension tables links to factory registration keys:

```
Definition.code_ref → FACTORY.build(code_ref) → Execution Object
```

**Service Pattern**:
1. Load Instance from DB
2. Load related Definition(s)
3. Get `code_ref` from Definition extension table
4. Call `FACTORY.build(code_ref, config)` to instantiate
5. Execute domain logic

**Factories** (libs/data/registry.py):
- PIPELINE_FACTORY, STORE_FACTORY, ACCESSOR_FACTORY, OPS_REGISTRY

**Seeding** (scripts/seed_definitions.py):
- Built-in definitions seeded at startup with code_ref matching factory keys

## 6. API Layer (Phase 4)

### Routers
Location: `apps/api/routers/`
- `ops.py` - `/ops` endpoints (list, get, evaluate)
- `pipelines.py` - `/pipelines` endpoints (definitions, instances, runs)
- `experiments.py` - `/experiments` endpoints (create, run, save-as-macro)
- `datasets.py` - `/datasets` endpoints (status, preview, refresh)
- `signals.py` - `/signals` endpoints (register, validate, promote)

### Services
Location: `apps/api/services/`
- `DatasetService` - get_status, preview, refresh
- `SignalService` - register_signal, validate_signal, promote_signal
- `PipelineService` - submit_definition, deploy_definition, create_instance, trigger_run
- `ExperimentService` - create_experiment, run_experiment, save_as_macro
- `OpService` - list_operators, get_operator, evaluate_expression

### Schemas
Location: `apps/api/schemas.py` (Quant Domain section)

### Router Pattern
```python
# 1. Get resource and check RBAC
resource = await get_resource_or_404(db, actor.tenant_id, id)
await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)
# 2. Call service (services emit activities, NOT routers)
service = DatasetService()
result = await service.preview(session=db, actor=actor, ...)
# 3. Return DTO (never SQLAlchemy models)
return DatasetPreviewOut(**result)
```

## 7. References

See `.claude/skills/quant-resource-patterns/` for complete patterns:
- `SKILL.md` - Full resource implementation guide
- `references/db-patterns.md` - SQLAlchemy patterns
- `references/dto-patterns.md` - Pydantic schemas
- `references/service-patterns.md` - CRUD with activities
