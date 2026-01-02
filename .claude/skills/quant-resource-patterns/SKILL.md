---
name: quant-resource-patterns
description: Follow these patterns when implementing quant domain resources like Dataset, Signal, Alpha, Portfolio, Strategy, Universe, Backtest, or MonitoringRun in OptAIC. Use for creating DB models, DTOs, services, and tests for trading-specific entities.
---

# Quant Resource Implementation Patterns

Guide for implementing domain resources that integrate with OptAIC's resource-based architecture.

## When to Use

Apply when:
- Creating new domain resource types (Dataset, Signal, Portfolio, etc.)
- Implementing Definition resources (PipelineDef, StoreDef, OpDef, MLModuleDef, PortfolioOptimizerDef)
- Implementing Instance resources (DatasetInstance, SignalInstance, BacktestInstance, etc.)
- Implementing Run resources (BacktestRun, TrainingRun, MonitoringRun, etc.)
- Adding domain-specific DB models, DTOs, or services

## Three-Tier Resource Model

OptAIC separates **Definitions** (plugins) from **Instances** (configs) from **Runs** (executions):

```
Definition (Plugin)         Instance (Config)              Run (Execution)
─────────────────          ──────────────────             ────────────────
BloombergPipelineDef   →   SPX_OHLCV_Dataset          →   PipelineRun (daily)
PortfolioOptimizerDef  →   MVO_Conservative           →   PortfolioOptimizationRun
MLModuleDef            →   XGBoost_Predictor          →   TrainingRun, InferenceRun, MonitoringRun
(none)                 →   BacktestInstance           →   BacktestRun
```

**Definitions**: Reusable building blocks submitted as plugins (the "Law")
**Instances**: Concrete configurations referencing definitions
**Runs**: Executions that produce immutable versions and metrics

## Resource Type Summary

### Definition Resources
| Type | Purpose | Contains |
|------|---------|----------|
| `PipelineDef` | Data ingestion plugin | ETL code, schemas |
| `StoreDef` | Storage backend | Parquet/SQLite/Virtual |
| `AccessorDef` | Data access pattern | Simple/PIT/Field |
| `OpDef` | Math operator | REF, DELTA, MEAN |
| `OpMacroDef` | Saved expression | User formulas |
| `MLModuleDef` | ML model template | XGBoost, LSTM |
| `PortfolioOptimizerDef` | Optimization algo | MVO, HRP, RiskParity |

### Instance Resources
| Type | Parent Definition | Notes |
|------|-------------------|-------|
| `DatasetInstance` | PipelineDef + StoreDef + AccessorDef | Composition |
| `SignalInstance` | Inherits DatasetInstance | Promoted dataset |
| `ExperimentInstance` | OpDef/OpMacroDef | Expression config |
| `ModelInstance` | MLModuleDef | ML model config |
| `PortfolioOptimizerInstance` | PortfolioOptimizerDef | Optimizer config |
| `BacktestInstance` | None | Fixed procedure |

### Run Resources
| Type | Parent Instance | Key Outputs |
|------|-----------------|-------------|
| `PipelineRun` | DatasetInstance | rows_added, last_date |
| `ExperimentRun` | ExperimentInstance | preview_data |
| `BacktestRun` | BacktestInstance | equity_curve, trades, metrics |
| `PortfolioOptimizationRun` | PortfolioOptimizerInstance | weights |
| `TrainingRun` | ModelInstance | model_artifact |
| `InferenceRun` | ModelInstance | predictions |
| `MonitoringRun` | ModelInstance/DatasetInstance | drift_metrics, alerts |

## Implementation Workflow

### 1. Determine Resource Tier

**Definition resource?** → Implements abstract interface, has test suite, requires evaluation
**Instance resource?** → References definition(s), has config, can be scheduled

### 2. Create DB Model

Location: `libs/db/models/<domain>.py`

Link to resources table via FK. See [references/db-patterns.md](references/db-patterns.md).

### 3. Create DTOs

Location: `libs/core/domain/<domain>.py`

Use Pydantic. Never expose SQLAlchemy models to API. See [references/dto-patterns.md](references/dto-patterns.md).

### 4. Create Service Layer

Location: `libs/core/domain/<domain>_service.py`

Emit activities for all mutations. See [references/service-patterns.md](references/service-patterns.md).

### 5. Register ResourceType

Update `libs/core/resources.py` → `ResourceType` enum.

### 6. Generate Migration

```bash
optaic db revision --autogenerate -m "add <domain> resource"
```

### 7. Write Tests

Location: `libs/core/tests/test_<domain>.py`

## Critical Rules

1. **Lazy imports** - Heavy deps (pandas, numpy, torch) must use `TYPE_CHECKING` blocks
2. **Activity emission** - All mutations emit activities in service layer
3. **Guardrails hooks** - Validate at lifecycle gates (create/update/promote)
4. **Version tracking** - Instances reference definition versions
5. **code_ref linkage** - Services bridge DB models to factories via `Definition.code_ref`

## code_ref Integration (CRITICAL)

The `code_ref` field in Definition extension tables links to factory registration keys:

```
Definition.code_ref → FACTORY.build(code_ref) → Execution Object
```

**Pattern**: Service loads Instance → loads Definition → gets `code_ref` → builds from Factory

See [Service Patterns](references/service-patterns.md) for implementation details.

## Reference Files

- [DB Model Patterns](references/db-patterns.md) - SQLAlchemy patterns
- [DTO Patterns](references/dto-patterns.md) - Pydantic schemas
- [Service Patterns](references/service-patterns.md) - CRUD with activities
