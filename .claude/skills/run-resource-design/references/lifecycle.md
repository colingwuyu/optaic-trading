# Run Lifecycle Patterns

Status transitions and activity emission for Run resources.

## Status State Machine

```
                        ┌──────────────┐
                        │   pending    │
                        └──────┬───────┘
                               │ start()
                        ┌──────▼───────┐
                    ┌───│   running    │───┐
                    │   └──────────────┘   │
             complete()                 fail()
                    │                      │
             ┌──────▼───────┐      ┌───────▼──────┐
             │  completed   │      │    failed    │
             └──────────────┘      └──────────────┘

Additional transitions:
- pending → cancelled (user cancellation)
- running → cancelled (user cancellation)
```

## Valid Transitions

| From | To | Trigger |
|------|-----|---------|
| `pending` | `running` | Worker picks up job |
| `pending` | `cancelled` | User cancels |
| `running` | `completed` | Execution succeeds |
| `running` | `failed` | Execution errors |
| `running` | `cancelled` | User cancels |

## Lifecycle Implementation

```python
class RunLifecycle:
    VALID_TRANSITIONS = {
        "pending": ["running", "cancelled"],
        "running": ["completed", "failed", "cancelled"],
        "completed": [],
        "failed": [],
        "cancelled": [],
    }

    async def transition(
        self,
        db: AsyncSession,
        run: Resource,
        new_status: str,
        actor: ActorContext,
        **kwargs,
    ) -> Resource:
        current = run.status
        if new_status not in self.VALID_TRANSITIONS.get(current, []):
            raise InvalidTransition(f"Cannot transition {current} → {new_status}")

        # Update status
        run.status = new_status

        # Set timing fields
        if new_status == "running":
            run.metadata_json["started_at"] = datetime.utcnow().isoformat()
        elif new_status in ("completed", "failed", "cancelled"):
            run.metadata_json["ended_at"] = datetime.utcnow().isoformat()

        # Set error info if failed
        if new_status == "failed" and "error" in kwargs:
            run.metadata_json["error"] = kwargs["error"]

        # Emit activity
        await self._emit_transition_activity(db, run, current, new_status, actor, kwargs)

        await db.flush()
        return run

    async def _emit_transition_activity(
        self,
        db: AsyncSession,
        run: Resource,
        from_status: str,
        to_status: str,
        actor: ActorContext,
        kwargs: dict,
    ):
        action_map = {
            ("pending", "running"): "run.started",
            ("running", "completed"): "run.completed",
            ("running", "failed"): "run.failed",
            ("pending", "cancelled"): "run.cancelled",
            ("running", "cancelled"): "run.cancelled",
        }

        action = action_map.get((from_status, to_status))
        if not action:
            return

        payload = {
            "from_status": from_status,
            "to_status": to_status,
        }

        if to_status == "completed" and "metrics" in kwargs:
            payload["metrics"] = kwargs["metrics"]
        if to_status == "failed" and "error" in kwargs:
            payload["error"] = str(kwargs["error"])[:1000]

        await record_activity_with_outbox(
            db,
            ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=run.id,
                resource_type=run.type,
                action=action,
                payload=payload,
            )
        )
```

## Activity Events

### Run Started
```python
ActivityEnvelope(
    action="backtest.started",
    resource_id=run_id,
    resource_type="BacktestRun",
    payload={
        "instance_id": str(backtest_instance_id),
        "date_range": {"start": "2024-01-01", "end": "2024-03-31"},
        "worker_id": "worker-1"
    }
)
```

### Progress Update
```python
ActivityEnvelope(
    action="backtest.progress",
    resource_id=run_id,
    payload={
        "progress_pct": 45.5,
        "current_date": "2024-02-15",
        "trades_executed": 120
    }
)
```

### Run Completed
```python
ActivityEnvelope(
    action="backtest.completed",
    resource_id=run_id,
    payload={
        "duration_seconds": 45.2,
        "metrics": {
            "sharpe_ratio": 1.85,
            "max_drawdown": -0.12
        },
        "outputs_ref": "s3://runs/abc123/"
    }
)
```

### Run Failed
```python
ActivityEnvelope(
    action="backtest.failed",
    resource_id=run_id,
    payload={
        "error_type": "DataNotFoundError",
        "error_message": "Signal data missing for 2024-02-01",
        "failed_at_date": "2024-02-01",
        "stack_trace_ref": "s3://logs/abc123/traceback.txt"
    }
)
```

## Real-time Updates via Centrifugo

```python
# Publish progress to run-specific channel
await centrifugo.publish(
    channel=f"run:{run_id}:progress",
    data={
        "progress_pct": 45.5,
        "current_date": "2024-02-15"
    }
)

# Publish completion to instance channel
await centrifugo.publish(
    channel=f"instance:{instance_id}:runs",
    data={
        "event": "run_completed",
        "run_id": str(run_id),
        "metrics": metrics
    }
)
```
