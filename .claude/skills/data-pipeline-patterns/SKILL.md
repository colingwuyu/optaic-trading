---
name: data-pipeline-patterns
description: Follow these patterns when implementing data pipelines, ETL, data ingestion, or data validation in OptAIC. Use for point-in-time (PIT) correctness, Arrow schemas, quality checks, and Prefect orchestration.
---

# Data Pipeline Patterns

Guide for implementing data pipelines that integrate with OptAIC's orchestration and governance.

## When to Use

Apply when:
- Building PipelineDef implementations (ETL, Expression, Training)
- Implementing data ingestion flows
- Creating data quality validation
- Setting up Arrow schemas for datasets
- Integrating with Prefect orchestration

## Pipeline Definition Types

| Type | Purpose | Input | Output |
|------|---------|-------|--------|
| ETL | External data ingestion | API/files | Dataset version |
| Expression | DSL transformation | Datasets | Derived dataset |
| Training | Model training | Datasets | Model artifact |
| Inference | Model prediction | Features + model | Prediction dataset |
| Monitoring | Quality/drift checks | Datasets | Metrics + alerts |

## Point-in-Time (PIT) Correctness

**Critical rule**: Always track `knowledge_date` (when data was known) separately from `as_of_date` (data's effective date).

```python
# WRONG - lookahead bias
df = pd.read_sql("SELECT * FROM prices WHERE date = ?", [target_date])

# CORRECT - PIT query
df = pd.read_sql("""
    SELECT * FROM prices
    WHERE as_of_date <= ?
    AND knowledge_date <= ?
    ORDER BY knowledge_date DESC
""", [target_date, knowledge_cutoff])
```

See [references/pit-patterns.md](references/pit-patterns.md).

## Arrow Schema Pattern

```python
import pyarrow as pa

def price_schema() -> pa.Schema:
    return pa.schema([
        pa.field("date", pa.date32(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("knowledge_date", pa.timestamp("us"), nullable=False),
    ])
```

## Prefect Integration

```python
from prefect import flow, task

@task
async def fetch_data(source: str, date: str) -> dict:
    pass

@task
async def validate_schema(data: dict, schema_ref: str) -> bool:
    pass

@flow
async def daily_refresh(dataset_id: UUID, date: str):
    raw = await fetch_data(...)
    if not await validate_schema(raw, schema_ref):
        raise ValidationError()
    await store_data(raw, dataset_id)
    await emit_activity("dataset.refreshed", ...)
```

See [references/prefect-patterns.md](references/prefect-patterns.md).

## Lineage and Freshness Checking

Before executing a pipeline, check upstream freshness:

```python
from libs.orchestration import (
    LineageResolver,
    FreshnessChecker,
    UpstreamNotReadyError,
)

async def run_with_lineage_check(session, dataset_id, force=False):
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

    # Execute pipeline
    result = await execute_pipeline(dataset_id)

    # On success, propagate staleness to downstream
    await resolver.propagate_staleness(session, dataset_id)
```

## UpdateFrequency Configuration

Configure expected update frequency for freshness calculations:

```python
from libs.orchestration import UpdateFrequency

# Daily data, 1 day grace period
frequency = UpdateFrequency(
    frequency="daily",
    grace_period_days=1,
)

# Business days only (skip weekends)
frequency = UpdateFrequency(
    frequency="daily",
    business_days_only=True,
    grace_period_days=1,
)

# Weekly on Monday
frequency = UpdateFrequency(
    frequency="weekly",
    day_of_week=0,  # 0=Monday
)

# Store in Instance config_json
config = {
    "update_frequency": {
        "frequency": "daily",
        "business_days_only": True,
        "grace_period_days": 1,
    }
}
```

See [references/lineage-patterns.md](references/lineage-patterns.md).

## Data Quality Checks

Standard checks to implement:
- `no_future_dates` - Prevent lookahead
- `no_duplicates` - Key uniqueness
- `coverage_check` - Required dates/symbols
- `schema_conformance` - Arrow schema match

See [references/quality-checks.md](references/quality-checks.md).

## Lazy Import Rule

Heavy deps must be lazy-loaded:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa
```

## Reference Files

- [PIT Patterns](references/pit-patterns.md) - Point-in-time correctness
- [Prefect Patterns](references/prefect-patterns.md) - Orchestration integration
- [Quality Checks](references/quality-checks.md) - Data validation
- [Lineage Patterns](references/lineage-patterns.md) - Dependency and freshness tracking
