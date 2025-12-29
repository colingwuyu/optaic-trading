# Contract Schema Patterns

## Basic Schema Structure

```python
SIGNAL_BOUNDS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "min_value": {
            "type": "number",
            "description": "Minimum allowed signal value"
        },
        "max_value": {
            "type": "number",
            "description": "Maximum allowed signal value"
        },
        "allow_nan": {
            "type": "boolean",
            "default": False
        }
    },
    "required": ["min_value", "max_value"],
    "additionalProperties": False
}
```

## Common Contract Schemas

### Dataset PIT Contract

```python
DATASET_PIT_SCHEMA = {
    "type": "object",
    "properties": {
        "knowledge_date_column": {
            "type": "string",
            "default": "knowledge_date"
        },
        "as_of_date_column": {
            "type": "string",
            "default": "date"
        },
        "max_staleness_days": {
            "type": "integer",
            "minimum": 0
        },
        "require_monotonic_knowledge": {
            "type": "boolean",
            "default": True
        }
    },
    "required": ["knowledge_date_column", "as_of_date_column"]
}
```

### Dataset Schema Contract

```python
DATASET_SCHEMA_CONTRACT = {
    "type": "object",
    "properties": {
        "arrow_schema_ref": {
            "type": "string",
            "description": "Reference to registered Arrow schema"
        },
        "required_columns": {
            "type": "array",
            "items": {"type": "string"}
        },
        "nullable_columns": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["arrow_schema_ref"]
}
```

### Portfolio Constraints Contract

```python
PORTFOLIO_CONSTRAINTS_SCHEMA = {
    "type": "object",
    "properties": {
        "sum_to_one": {
            "type": "boolean",
            "default": True
        },
        "sum_tolerance": {
            "type": "number",
            "default": 0.001
        },
        "long_only": {
            "type": "boolean",
            "default": False
        },
        "min_weight": {"type": "number"},
        "max_weight": {"type": "number"},
        "max_positions": {
            "type": "integer",
            "minimum": 1
        },
        "max_gross_leverage": {
            "type": "number",
            "minimum": 0
        }
    }
}
```

### Freshness Contract

```python
DATASET_FRESHNESS_SCHEMA = {
    "type": "object",
    "properties": {
        "expected_cadence": {
            "type": "string",
            "enum": ["daily", "weekly", "monthly", "irregular"]
        },
        "max_staleness_hours": {
            "type": "integer",
            "minimum": 1
        },
        "grace_period_hours": {
            "type": "integer",
            "minimum": 0,
            "default": 0
        },
        "check_schedule": {
            "type": "string",
            "description": "Cron expression for freshness checks"
        }
    },
    "required": ["expected_cadence", "max_staleness_hours"]
}
```
