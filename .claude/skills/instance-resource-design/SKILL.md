---
name: instance-resource-design
description: Guide for designing Instance resources in OptAIC. Use when creating DatasetInstance, SignalInstance, ExperimentInstance, ModelInstance, PortfolioOptimizerInstance, or BacktestInstance. Covers definition references, config patterns, composition, and scheduling.
---

# Instance Resource Design Patterns

Guide for designing Instance resources that configure and execute Definition plugins.

## When to Use

Apply when:
- Creating configured dataset/signal/model instances
- Designing composition patterns (Pipeline + Store + Accessor)
- Implementing scheduling and freshness tracking
- Building special cases like BacktestInstance (no definition)

## Core Concept: Configured Usage

Instances reference Definitions and provide runtime configuration:

```
Instance = Configured Usage
├── definition_resource_id    # Which Definition to use
├── definition_version_id     # Pinned version (optional)
├── config_json               # Runtime configuration
├── schedule_json             # Cron/refresh schedule
└── upstream_refs             # Connected upstream resources
```

## Instance Types

| Type | Parent | Definition Ref | Notes |
|------|--------|---------------|-------|
| `DatasetInstance` | Project | PipelineDef + StoreDef + AccessorDef | Composition |
| `SignalInstance` | Project | Inherits from DatasetInstance | Promoted dataset |
| `ExperimentInstance` | Project | OpDef/OpMacroDef | Expression config |
| `ModelInstance` | Project | MLModuleDef | ML model config |
| `PortfolioOptimizerInstance` | Project | PortfolioOptimizerDef | Optimizer config |
| `BacktestInstance` | Project | None | Fixed procedure |

## Composition Pattern

DatasetInstance composes multiple definitions:

```
DatasetInstance
├── pipeline_instance_id  → PipelineInstance → PipelineDef
├── store_instance_id     → StoreInstance → StoreDef
└── accessor_instance_id  → AccessorInstance → AccessorDef
```

See [references/composition.md](references/composition.md).

## Config Structure

```python
instance_metadata = {
    "definition_resource_id": "uuid",
    "definition_version_id": "uuid (optional)",

    "config_json": {
        "symbols": ["AAPL", "MSFT", "GOOGL"],
        "start_date": "2020-01-01",
        "lookback_days": 252
    },

    "schedule_json": {
        "type": "cron",
        "expression": "0 6 * * 1-5",
        "timezone": "America/New_York"
    },

    "upstream_refs": [
        {"resource_id": "uuid", "role": "input"},
        {"resource_id": "uuid", "role": "covariance"}
    ]
}
```

## Special Case: BacktestInstance

BacktestInstance has no Definition - the backtest procedure is fixed:

```python
backtest_instance = {
    "type": "BacktestInstance",
    "name": "Q1_2024_Backtest",
    "metadata_json": {
        # No definition_resource_id

        "assets_json": {
            "universe": ["SPY", "QQQ", "IWM"],
            "benchmark": "SPY"
        },

        "signals_json": {
            "primary": "uuid-of-signal-instance",
            "secondary": ["uuid-1", "uuid-2"]
        },

        "date_range_json": {
            "start": "2024-01-01",
            "end": "2024-03-31"
        },

        "config_json": {
            "rebalance_frequency": "daily",
            "transaction_costs": 0.001,
            "slippage_model": "linear"
        }
    }
}
```

## Implementation Checklist

1. [ ] Reference parent Definition via `definition_resource_id`
2. [ ] Pin version if reproducibility needed (`definition_version_id`)
3. [ ] Design `config_json` matching Definition's `parameters_schema`
4. [ ] Track `upstream_refs` for lineage
5. [ ] Add freshness tracking fields if scheduled
6. [ ] Create extension table in `libs/db/models/`

## Reference Files

- [Composition](references/composition.md) - Dataset composition pattern
- [Examples](references/examples.md) - Complete Instance examples
- [Scheduling](references/scheduling.md) - Schedule configuration
