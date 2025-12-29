# Activity Payload Examples

## Creation Events

```python
# signal.created
payload = {
    "signal_type": "alpha",
    "frequency": "daily",
    "lookback_days": 20
}

# dataset_instance.created
payload = {
    "pipeline_def": "bloomberg-pipeline",
    "store_def": "parquet-store",
    "schedule": {"cron": "0 18 * * 1-5"}
}

# definition.submitted
payload = {
    "kind": "pipeline",
    "interface_version": "1.0",
    "test_count": 15
}
```

## Update Events

```python
# signal.updated
payload = {
    "changes": {
        "lookback_days": {"old": 20, "new": 30},
        "config.normalize": {"old": False, "new": True}
    }
}

# dataset.schedule_updated
payload = {
    "old_schedule": {"cron": "0 18 * * 1-5"},
    "new_schedule": {"cron": "0 6 * * 1-5"}
}
```

## Execution Events

```python
# run.started
payload = {
    "run_type": "refresh",
    "instance_id": "uuid",
    "triggered_by": "schedule"  # or "manual"
}

# run.completed
payload = {
    "duration_seconds": 145.3,
    "rows_processed": 50000,
    "output_version": "v123"
}

# run.failed
payload = {
    "error_code": "UPSTREAM_NOT_READY",
    "error_message": "Upstream dataset SPX_OHLCV not fresh",
    "duration_seconds": 2.1
}

# backtest.completed
payload = {
    "date_range": {"start": "2020-01-01", "end": "2024-01-01"},
    "metrics": {
        "sharpe_ratio": 1.45,
        "max_drawdown": -0.12,
        "total_return": 0.23
    }
}
```

## Governance Events

```python
# promotion.requested
payload = {
    "from_space": "personal",
    "to_space": "team:quant-research",
    "dependency_count": 5
}

# promotion.approved
payload = {
    "approver_id": "uuid",
    "ticket_id": "JIRA-123",
    "notes": "Passed review criteria"
}

# guardrails.validated
payload = {
    "report_id": "uuid",
    "scope": "promotion",
    "ok": True,
    "error_count": 0,
    "warning_count": 2
}

# guardrails.blocked
payload = {
    "report_id": "uuid",
    "reason": "Signal values exceed bounds",
    "blocked_action": "merge_to_official"
}
```

## Freshness Events

```python
# dataset.stale
payload = {
    "expected_update_at": "2024-01-15T18:00:00Z",
    "last_update_at": "2024-01-14T18:00:00Z",
    "staleness_hours": 24
}

# dataset.refreshed
payload = {
    "previous_version": "v122",
    "new_version": "v123",
    "rows_added": 500,
    "refresh_type": "incremental"
}
```

## What NOT to Include

```python
# BAD - contains sensitive data
payload = {
    "api_key": "sk-xxx",           # NO - secret
    "password": "hunter2",          # NO - credential
    "full_data": [...huge array...] # NO - too large
}

# GOOD - reference instead
payload = {
    "data_ref": "artifacts/data/v123.parquet",
    "row_count": 50000
}
```
