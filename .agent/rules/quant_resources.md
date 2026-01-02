---
trigger: model_decision
description: Agent trigger: Load this file when implementing quant domain resources like Dataset, Signal, Portfolio, Backtest, or any Definition/Instance/Run resource types.
---

# Quant Resource Patterns

Guide for implementing domain resources in OptAIC's resource-based architecture.

## 1. Three-Tier Resource Model

`
Definition (Plugin)         Instance (Config)              Run (Execution)
-------------------        ------------------             ----------------
BloombergPipelineDef   ->  SPX_OHLCV_Dataset          ->  PipelineRun
PortfolioOptimizerDef  ->  MVO_Conservative           ->  PortfolioOptimizationRun
MLModuleDef            ->  XGBoost_Predictor          ->  TrainingRun, InferenceRun
(none)                 ->  BacktestInstance           ->  BacktestRun
`

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

## 6. References

See `.claude/skills/quant-resource-patterns/` for complete patterns:
- `SKILL.md` - Full resource implementation guide
- `references/db-patterns.md` - SQLAlchemy patterns
- `references/dto-patterns.md` - Pydantic schemas
- `references/service-patterns.md` - CRUD with activities
