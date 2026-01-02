---
name: run-resource-design
description: Guide for designing Run resources in OptAIC. Use when creating PipelineRun, ExperimentRun, BacktestRun, PortfolioOptimizationRun, TrainingRun, InferenceRun, or MonitoringRun. Covers execution tracking, metrics, output artifacts, and lineage.
---

# Run Resource Design Patterns

Guide for designing Run resources that track execution results and produce versioned outputs.

## When to Use

Apply when:
- Creating execution tracking for pipeline/model/backtest runs
- Designing output artifact storage patterns
- Implementing metrics and status tracking
- Building lineage tracking for reproducibility

## Core Concept: Execution Record

Runs track execution of Instance resources:

```
Run = Execution Record
├── parent_instance_id    # Which Instance was executed
├── status                # pending|running|completed|failed
├── started_at / ended_at # Timing
├── metrics_json          # Computed metrics
├── outputs_ref           # Path to output artifacts
└── input_versions        # Versions of upstream resources used
```

## Run Types

| Type | Parent Instance | Key Outputs |
|------|----------------|-------------|
| `PipelineRun` | DatasetInstance | rows_added, last_date |
| `ExperimentRun` | ExperimentInstance | preview_data, statistics |
| `BacktestRun` | BacktestInstance | equity_curve, trades, metrics |
| `PortfolioOptimizationRun` | PortfolioOptimizerInstance | weights, metrics |
| `TrainingRun` | ModelInstance | model_artifact, metrics |
| `InferenceRun` | ModelInstance | predictions, confidence |
| `MonitoringRun` | ModelInstance/DatasetInstance | drift_metrics, alerts |

## Status Flow

```
pending → running → completed
                  ↘ failed
                  ↘ cancelled
```

## Run Lifecycle

1. **Submit**: Create Run in `pending`
2. **Start**: Transition to `running`, set `started_at`
3. **Progress**: Update `progress_pct`, emit activities
4. **Complete**: Set `ended_at`, store outputs, transition to `completed`
5. **Fail**: Set error info, transition to `failed`

See [references/lifecycle.md](references/lifecycle.md).

## Output Artifacts

```python
run_outputs = {
    "metrics_json": {
        "sharpe_ratio": 1.85,
        "max_drawdown": -0.12,
        "total_return": 0.15
    },

    "artifacts_ref": {
        "equity_curve": "s3://runs/{run_id}/equity_curve.parquet",
        "trades": "s3://runs/{run_id}/trades.parquet",
        "weights_history": "s3://runs/{run_id}/weights.parquet"
    }
}
```

## Lineage Tracking

Track which versions of upstream resources were used:

```python
input_versions = {
    "signal_instance_id": "uuid",
    "signal_version_id": "version-uuid",
    "price_dataset_version_id": "version-uuid",
    "model_artifact_version": "v1.2.3"
}
```

## Implementation Checklist

1. [ ] Create extension table with run-specific fields
2. [ ] Implement status transitions with validation
3. [ ] Track timing (started_at, ended_at)
4. [ ] Store metrics in `metrics_json`
5. [ ] Store large outputs externally (`artifacts_ref`)
6. [ ] Track input versions for lineage
7. [ ] Emit activities at lifecycle transitions

## Reference Files

- [Lifecycle](references/lifecycle.md) - Status transitions and activities
- [Examples](references/examples.md) - Complete Run examples
- [Metrics](references/metrics.md) - Standard metrics by run type
