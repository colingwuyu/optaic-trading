# Quant Domain API Reference

This document describes the REST API endpoints for the quant trading domain.

## Overview

The quant domain API provides endpoints for:
- **Operators**: Expression evaluation and operator metadata
- **Pipelines**: Data pipeline definition, configuration, and execution
- **Datasets**: Data preview, status, and refresh
- **Signals**: Signal registration, validation, and promotion
- **Experiments**: Expression experiments and macro creation

All endpoints require authentication and respect RBAC permissions.

## Base URL

```
http://localhost:8081/api
```

## Operators API

### List Operators

```http
GET /ops
```

Query parameters:
- `category` (optional): Filter by category (e.g., "rolling", "time_series")

Response:
```json
{
  "operators": [
    {
      "name": "MEAN",
      "category": "Rolling",
      "arity": 2,
      "description": "Rolling mean over N periods."
    }
  ],
  "count": 25
}
```

### Get Operator Details

```http
GET /ops/{name}
```

Response:
```json
{
  "name": "MEAN",
  "category": "Rolling",
  "arity": 2,
  "description": "Rolling mean over N periods."
}
```

### Evaluate Expression

```http
POST /ops/evaluate
```

Request body:
```json
{
  "expression": "MEAN($close, 20)",
  "context": {
    "close": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1"
  },
  "start_date": "2024-01-01",
  "end_date": "2024-12-31"
}
```

Response:
```json
{
  "success": true,
  "expression": "MEAN($close, 20)",
  "result_type": "dataframe",
  "columns": ["date", "value"],
  "data": [...],
  "row_count": 252,
  "truncated": false
}
```

## Pipelines API

### Submit Pipeline Definition

```http
POST /pipelines/definitions
```

Request body:
```json
{
  "name": "FRED Pipeline",
  "code_ref": "FREDPipeline",
  "category": "etl",
  "parent_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1",
  "interface_spec": "libs.data.pipelines.base.BasePipeline",
  "input_schema": {},
  "output_schema": {},
  "parameters_schema": {},
  "guardrail_contracts": []
}
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "FRED Pipeline",
  "code_ref": "FREDPipeline",
  "category": "etl",
  "status": "draft"
}
```

### Deploy Pipeline Definition

```http
POST /pipelines/definitions/{definition_id}/deploy
```

Changes definition status from `draft` to `active`.

### List Pipeline Definitions

```http
GET /pipelines/definitions
```

Query parameters:
- `category` (optional): Filter by category
- `status` (optional): Filter by status (draft, active)
- `limit` (optional): Max results (default 50)

### Create Pipeline Instance

```http
POST /pipelines/instances
```

Request body:
```json
{
  "name": "Daily FRED Update",
  "definition_id": "9b7e2b44-...",
  "parent_id": "9b7e2b44-...",
  "config": {"series_id": "GDP"},
  "schedule": {"cron": "0 6 * * *"}
}
```

### Trigger Pipeline Run

```http
POST /pipelines/instances/{instance_id}/run
```

### List Pipeline Instances

```http
GET /pipelines/instances
```

Query parameters:
- `parent_id` (optional): Filter by parent resource
- `status` (optional): Filter by status (idle, running)
- `limit` (optional): Max results

## Datasets API

### Get Dataset

```http
GET /datasets/{dataset_id}
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "SPX OHLCV",
  "freshness_status": "fresh",
  "last_data_date": "2024-12-31",
  "row_count": 5000
}
```

### Get Dataset Status

```http
GET /datasets/{dataset_id}/status
```

### Preview Dataset

```http
POST /datasets/{dataset_id}/preview
```

Request body:
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "as_of_date": "2024-06-15",
  "limit": 100
}
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "SPX OHLCV",
  "columns": ["date", "open", "high", "low", "close", "volume"],
  "data": [...],
  "row_count": 100,
  "truncated": true
}
```

### Refresh Dataset

```http
POST /datasets/{dataset_id}/refresh
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "SPX OHLCV",
  "status": "refreshing",
  "message": "Refresh queued"
}
```

## Signals API

### Register Signal

```http
POST /signals
```

Request body:
```json
{
  "dataset_id": "9b7e2b44-...",
  "name": "momentum_signal",
  "parent_id": "9b7e2b44-...",
  "min_value": -1.0,
  "max_value": 1.0,
  "allow_nan": false,
  "neutral_value": 0.0
}
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "momentum_signal",
  "min_value": -1.0,
  "max_value": 1.0,
  "allow_nan": false,
  "neutral_value": 0.0,
  "status": "staging"
}
```

### Get Signal

```http
GET /signals/{signal_id}
```

### Validate Signal

```http
POST /signals/{signal_id}/validate
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "valid": true,
  "issues": []
}
```

### Promote Signal

```http
POST /signals/{signal_id}/promote
```

Promotes signal from staging to official status.

### List Signals

```http
GET /signals
```

Query parameters:
- `parent_id` (optional): Filter by parent resource
- `status` (optional): Filter by status (staging, official)
- `limit` (optional): Max results

## Experiments API

### Create Experiment

```http
POST /experiments
```

Request body:
```json
{
  "name": "Momentum Strategy",
  "expression": "CORR($returns, REF($volume, 1), 20)",
  "parent_id": "9b7e2b44-...",
  "input_datasets": {
    "returns": "9b7e2b44-...",
    "volume": "9b7e2b44-..."
  },
  "description": "Test momentum-volume correlation"
}
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "Momentum Strategy",
  "expression": "CORR($returns, REF($volume, 1), 20)",
  "operators_used": ["CORR", "REF"],
  "datasets_referenced": ["returns", "volume"],
  "status": "created"
}
```

### Get Experiment

```http
GET /experiments/{experiment_id}
```

### Run Experiment

```http
POST /experiments/{experiment_id}/run
```

Request body:
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "limit": 100
}
```

Response:
```json
{
  "id": "a1b2c3d4-...",
  "success": true,
  "name": "Momentum Strategy",
  "expression": "CORR($returns, REF($volume, 1), 20)",
  "result_type": "dataframe",
  "columns": ["date", "value"],
  "data": [...],
  "row_count": 252,
  "truncated": false
}
```

### Update Experiment

```http
PATCH /experiments/{experiment_id}
```

Request body:
```json
{
  "expression": "CORR($returns, REF($volume, 5), 20)",
  "input_datasets": null
}
```

### Save Experiment as Macro

```http
POST /experiments/{experiment_id}/save-as-macro
```

Query parameters:
- `macro_name` (optional): Override name for the macro

Response:
```json
{
  "id": "a1b2c3d4-...",
  "name": "Macro_Momentum Strategy",
  "expression": "CORR($returns, REF($volume, 1), 20)",
  "input_aliases": ["returns", "volume"],
  "status": "saved"
}
```

### List Experiments

```http
GET /experiments
```

Query parameters:
- `parent_id` (optional): Filter by parent resource
- `limit` (optional): Max results

## Activity Events

All mutations emit activity events for audit trails:

| Action | Description |
|--------|-------------|
| `pipeline_def.submitted` | Pipeline definition created |
| `pipeline_def.deployed` | Pipeline definition deployed |
| `pipeline_instance.created` | Pipeline instance created |
| `pipeline.run_started` | Pipeline run triggered |
| `dataset.previewed` | Dataset data previewed |
| `dataset.refresh_started` | Dataset refresh triggered |
| `signal.registered` | Signal registered from dataset |
| `signal.validated` | Signal validated against spec |
| `signal.promoted` | Signal promoted to official |
| `experiment.created` | Experiment created |
| `experiment.run_completed` | Experiment run succeeded |
| `experiment.run_failed` | Experiment run failed |
| `experiment.updated` | Experiment updated |
| `expression.evaluated` | Expression evaluated |
| `macro.saved` | Experiment saved as macro |

## Error Responses

```json
{
  "detail": "Error message"
}
```

Common HTTP status codes:
- `400`: Bad request (invalid input)
- `403`: Forbidden (RBAC violation)
- `404`: Resource not found
- `500`: Internal server error
