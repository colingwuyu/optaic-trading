---
trigger: model_decision
description: Agent trigger: Load this file when implementing data pipelines, ETL, ingestion, PIT-correctness, Arrow schemas, or Prefect flows.
---

# Data Pipeline Rules

Guide for implementing data pipelines with PIT correctness and quality validation.

## 1. Pipeline Types

| Type | Purpose | Input | Output |
|------|---------|-------|--------|
| ETL | External data ingestion | API/files | Dataset version |
| Expression | DSL transformation | Datasets | Derived dataset |
| Training | Model training | Datasets | Model artifact |
| Inference | Model prediction | Features + model | Prediction dataset |
| Monitoring | Quality/drift checks | Datasets | Metrics + alerts |

## 2. Point-in-Time (PIT) Correctness

**Critical rule**: Always track `knowledge_date` separately from `as_of_date`.

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

## 3. Arrow Schema Pattern

Define schemas with `knowledge_date` field for PIT tracking.

## 4. Data Quality Checks

- `no_future_dates` - Prevent lookahead
- `no_duplicates` - Key uniqueness
- `coverage_check` - Required dates/symbols
- `schema_conformance` - Arrow schema match

## 5. Lazy Import Rule

Heavy deps must be lazy-loaded using `TYPE_CHECKING` blocks.

## 6. References

See `.claude/skills/data-pipeline-patterns/` for complete patterns:
- `SKILL.md` - Full pipeline implementation guide
- `references/pit-patterns.md` - Point-in-time correctness
- `references/prefect-patterns.md` - Orchestration integration
- `references/quality-checks.md` - Data validation
