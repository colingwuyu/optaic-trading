---
trigger: model_decision
description: Agent trigger: Load this file when implementing data pipelines, ETL, ingestion, PIT-correctness, Arrow schemas, or Prefect flows.
---

# Data Pipeline Implementation Rules

This document governs data pipeline development in OptAIC, ensuring point-in-time correctness and data quality.

## 1. Point-in-Time (PIT) Correctness

**Critical rule**: Always track `knowledge_date` (when data was known) separately from `as_of_date` (data's effective date).

`python
# WRONG - lookahead bias
df = pd.read_sql("SELECT * FROM prices WHERE date = ?", [target_date])

# CORRECT - PIT query
df = pd.read_sql("""
    SELECT * FROM prices
    WHERE as_of_date <= ?
    AND knowledge_date <= ?
    ORDER BY knowledge_date DESC
""", [target_date, knowledge_cutoff])
`

## 2. Arrow Schema Pattern

All datasets must define PyArrow schemas with required temporal fields:

`python
import pyarrow as pa

def price_schema() -> pa.Schema:
    return pa.schema([
        pa.field("date", pa.date32(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("knowledge_date", pa.timestamp("us"), nullable=False),
    ])
`

## 3. Prefect Integration

Use `@task` for units of work and `@flow` for orchestration:

`python
from prefect import flow, task

@task
async def fetch_data(source: str, date: str) -> dict:
    pass

@flow
async def daily_refresh(dataset_id: UUID, date: str):
    raw = await fetch_data(...)
    await validate_schema(raw)
    await store_data(raw, dataset_id)
    await emit_activity("dataset.refreshed", ...)
`

## 4. Data Quality Checks

Implement these standard checks:
- `no_future_dates` - Prevent lookahead
- `no_duplicates` - Key uniqueness  
- `coverage_check` - Required dates/symbols present
- `schema_conformance` - Arrow schema match

## 5. Lazy Import Rule

Heavy deps must be lazy-loaded:

`python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa
`

## 6. Pipeline Definition Types

| Type | Purpose | Input | Output |
|------|---------|-------|--------|
| ETL | External data ingestion | API/files | Dataset version |
| Expression | DSL transformation | Datasets | Derived dataset |
| Training | Model training | Datasets | Model artifact |
| Inference | Model prediction | Features + model | Prediction dataset |