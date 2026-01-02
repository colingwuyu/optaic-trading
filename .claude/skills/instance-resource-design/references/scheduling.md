# Instance Scheduling Patterns

Configure refresh schedules for Instance resources.

## Schedule Schema

```json
{
  "schedule_json": {
    "type": "cron|interval|manual",
    "expression": "0 6 * * 1-5",
    "timezone": "America/New_York",
    "enabled": true,
    "retry_policy": {
      "max_retries": 3,
      "backoff": "exponential"
    }
  }
}
```

## Schedule Types

### Cron

```json
{
  "type": "cron",
  "expression": "0 6 * * 1-5",
  "timezone": "America/New_York"
}
```

Common patterns:
- `"0 6 * * 1-5"` - 6am ET weekdays
- `"0 18 * * *"` - 6pm daily
- `"0 0 * * 0"` - Midnight Sunday

### Interval

```json
{
  "type": "interval",
  "interval_minutes": 60,
  "start_time": "09:30",
  "end_time": "16:00",
  "timezone": "America/New_York"
}
```

### Manual

```json
{
  "type": "manual"
}
```

## Freshness Tracking

```sql
ALTER TABLE dataset_instances ADD COLUMN
    freshness_status VARCHAR(50) DEFAULT 'unknown',  -- fresh|stale|unknown|refreshing
    last_refresh_at TIMESTAMP WITH TIME ZONE,
    last_refresh_run_id UUID REFERENCES resources(id),
    next_refresh_at TIMESTAMP WITH TIME ZONE;
```

### Freshness States

| State | Meaning |
|-------|---------|
| `fresh` | Data current, within SLA |
| `stale` | Data behind schedule |
| `unknown` | Never refreshed |
| `refreshing` | Refresh in progress |
| `failed` | Last refresh failed |

## Prefect Integration

```python
from prefect import flow, task
from prefect.schedules import CronSchedule

@task
async def refresh_dataset(dataset_id: UUID, tenant_id: UUID):
    async with get_session() as db:
        instance = await get_dataset_instance(db, dataset_id)
        pipeline = await load_pipeline(db, instance.pipeline_instance_id)
        result = await pipeline.run(instance.config_json)
        await update_freshness(db, dataset_id, result)


def create_scheduled_flow(schedule_json: dict, dataset_id: UUID):
    schedule = CronSchedule(
        cron=schedule_json["expression"],
        timezone=schedule_json["timezone"]
    )

    @flow(schedule=schedule)
    async def dataset_refresh_flow():
        await refresh_dataset(dataset_id, tenant_id)

    return dataset_refresh_flow
```

## Activity Events

```python
# Scheduled refresh started
ActivityEnvelope(
    action="dataset.refresh_started",
    payload={
        "trigger": "scheduled",
        "schedule_expression": "0 6 * * 1-5"
    }
)

# Manual refresh started
ActivityEnvelope(
    action="dataset.refresh_started",
    payload={
        "trigger": "manual",
        "requested_by": str(actor.id)
    }
)

# Refresh completed
ActivityEnvelope(
    action="dataset.refresh_completed",
    payload={
        "rows_added": 100,
        "last_data_date": "2024-12-31",
        "duration_seconds": 45.2
    }
)

# Freshness alert
ActivityEnvelope(
    action="dataset.stale_alert",
    payload={
        "expected_refresh_at": "2024-12-31T06:00:00Z",
        "hours_overdue": 2.5
    }
)
```
