# Definition Schema Structure

Complete JSON Schema specification for Definition resource metadata.

## Top-Level Structure

```json
{
  "interface_spec": "string (required)",
  "version": "string (semver)",
  "input_schema": "object (JSON Schema)",
  "output_schema": "object",
  "compatibility_rules": "object",
  "guardrail_contracts": "array",
  "parameters_schema": "object (JSON Schema)",
  "test_suite_ref": "string (optional)"
}
```

## interface_spec

Python import path to abstract base class:

```
"interface_spec": "optaic.interfaces.BasePipeline"
"interface_spec": "optaic.interfaces.BaseStore"
"interface_spec": "optaic.interfaces.BaseAccessor"
"interface_spec": "optaic.interfaces.BaseOperator"
"interface_spec": "optaic.interfaces.BaseOptimizer"
```

## input_schema

JSON Schema defining expected inputs:

```json
{
  "input_schema": {
    "type": "object",
    "properties": {
      "datasets": {
        "type": "array",
        "items": {"$ref": "#/components/DatasetInstance"}
      },
      "lookback_days": {
        "type": "integer",
        "minimum": 1,
        "default": 252
      }
    },
    "required": ["datasets"]
  }
}
```

## output_schema

Structure of produced output:

```json
{
  "output_schema": {
    "type": "DataFrame",
    "columns": [
      {"name": "date", "dtype": "datetime64[ns]"},
      {"name": "entity", "dtype": "string"},
      {"name": "value", "dtype": "float64"}
    ],
    "constraints": {
      "value_range": {"min": -1, "max": 1},
      "no_future_dates": true
    }
  }
}
```

## compatibility_rules

Graph connection rules:

```json
{
  "compatibility_rules": {
    "upstream_types": ["DatasetInstance", "SignalInstance"],
    "upstream_min": 1,
    "upstream_max": 10,
    "downstream_types": ["SignalInstance", "BacktestInstance", "ExperimentInstance"],
    "required_upstream_contracts": ["pit.policy"]
  }
}
```

## guardrail_contracts

Embedded validation rules (the "Law"):

```json
{
  "guardrail_contracts": [
    {
      "kind": "signal.bounds",
      "config": {
        "min": -1,
        "max": 1,
        "allow_nan": false,
        "clamp_on_violation": false
      },
      "enforcement": "block"
    },
    {
      "kind": "pit.policy",
      "config": {
        "knowledge_date_required": true,
        "max_staleness_days": 1
      },
      "enforcement": "block"
    },
    {
      "kind": "dataset.schema",
      "config": {
        "required_columns": ["date", "entity", "value"],
        "allow_extra_columns": true
      },
      "enforcement": "warn"
    }
  ]
}
```

### Contract Kinds

| Kind | Purpose | Typical Config |
|------|---------|----------------|
| `signal.bounds` | Value range limits | `min`, `max`, `allow_nan` |
| `pit.policy` | Point-in-time correctness | `knowledge_date_required` |
| `dataset.schema` | Column validation | `required_columns`, `dtypes` |
| `dataset.freshness` | Staleness SLA | `max_staleness_days` |
| `portfolio.weights` | Weight constraints | `sum_to_one`, `min_weight`, `max_weight` |
| `portfolio.leverage` | Exposure limits | `max_gross`, `max_net` |

## parameters_schema

Plugin configuration parameters:

```json
{
  "parameters_schema": {
    "type": "object",
    "properties": {
      "api_key_ref": {"type": "string", "format": "secret-ref"},
      "symbols": {"type": "array", "items": {"type": "string"}},
      "start_date": {"type": "string", "format": "date"}
    },
    "required": ["api_key_ref", "symbols"]
  }
}
```

## Extension Table Schema

```sql
CREATE TABLE pipeline_definitions (
    resource_id UUID PRIMARY KEY REFERENCES resources(id),
    category VARCHAR(100) NOT NULL,        -- "etl", "expression", "transform"
    interface_spec VARCHAR(255) NOT NULL,
    code_ref VARCHAR(1024),                -- S3/Git path to implementation
    input_schema JSONB,
    output_schema JSONB,
    compatibility_rules JSONB,
    guardrail_contracts JSONB,
    parameters_schema JSONB,
    test_suite_ref VARCHAR(1024)
);
```
