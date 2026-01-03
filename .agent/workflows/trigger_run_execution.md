---
description: Workflow to trigger and manage Run executions (PipelineRun, TrainingRun, etc.).
---

# Trigger Run Execution Workflow

Follow this workflow when implementing run execution for any Instance type.

## 0. Understand the Model

```
Instance (static)
    ↓ has
Flow Execution Resource (static, Prefect deployment)
    ↓ triggers
Run (dynamic, Prefect flow run)
```

## 1. Check Upstream Freshness

Before triggering a run, check upstream dependencies:

```python
from libs.orchestration import (
    LineageResolver, FreshnessChecker, UpstreamNotReadyError
)

resolver = LineageResolver()
checker = FreshnessChecker(status_store)

report = await resolver.check_upstream_freshness(
    session, resource_id, checker
)

if not report.all_ready and not force:
    raise UpstreamNotReadyError(
        f"{len(report.blocking_resources)} upstream(s) not ready",
        blocking_resources=report.blocking_resources,
    )
```

## 2. Validate at Guardrails Gate

```python
await guardrails_engine.validate_at_gate(
    db=session,
    scope="run",
    target_id=str(run_id),
    resource_id=str(instance_id),
    context=guardrails_context,
    target_snapshot={"mode": mode},
)
```

## 3. Create Run Resource Record

```python
run = PipelineRun(
    resource_id=run_resource.id,
    tenant_id=actor.tenant_id,
    dataset_instance_id=instance_id,
    mode=mode,
    status="pending",
)
session.add(run)
await session.flush()
```

## 4. Submit to Orchestrator

```python
result = await orchestrator.submit_run(
    run_id=run.id,
    deployment_id=instance.prefect_deployment_id,
    parameters={"mode": mode, **config},
    tags={"tenant_id": str(actor.tenant_id)},
)

run.orchestrator_run_id = result.orchestrator_run_id
run.orchestrator_kind = result.orchestrator_kind
run.status = "running"
run.started_at = datetime.utcnow()
```

## 5. Emit Activity

```python
await emit_activity(
    action="pipeline_run.started",
    resource_id=run.id,
    payload={
        "orchestrator_run_id": result.orchestrator_run_id,
        "mode": mode,
    },
)
```

## 6. Poll and Sync Status

Implement status polling (or webhook handler):

```python
async def poll_and_sync(session, run_id):
    run = await session.get(PipelineRun, run_id)

    if run.status in ("completed", "failed", "cancelled"):
        return run  # Terminal state

    status = await orchestrator.get_status(run.orchestrator_run_id)

    if status.status != run.status:
        run.status = status.status
        run.finished_at = status.finished_at
        run.error_summary = status.error_message
        await session.commit()

        if status.status == "completed":
            await _on_run_completed(session, run)
        elif status.status == "failed":
            await _on_run_failed(session, run, status.error_message)

    return run
```

## 7. Handle Run Completion

```python
async def _on_run_completed(session, run):
    # 1. Update Instance's freshness status
    instance = await session.get(DatasetInstance, run.dataset_instance_id)
    instance.freshness_status = "ready"
    instance.last_run_at = run.finished_at

    # 2. Update StatusStore for freshness calculations
    await status_store.mark_run_success(
        resource_id=instance.resource_id,
        last_data_date=run.metrics_json.get("last_data_date"),
        rows_processed=run.metrics_json.get("rows_processed"),
    )

    # 3. Propagate staleness to downstream resources
    resolver = LineageResolver()
    affected = await resolver.propagate_staleness(session, instance.resource_id)

    # 4. Publish real-time status update
    await centrifugo.publish(
        channel=f"instance:{instance.resource_id}:status",
        data={"status": "ready", "last_run_id": str(run.id)},
    )

    # 5. Emit completion activity
    await emit_activity(
        "pipeline_run.completed",
        run.id,
        {"metrics": run.metrics_json, "affected_downstream": [str(r) for r in affected]},
    )
```

## 8. Handle Run Failure

```python
async def _on_run_failed(session, run, error_message):
    # 1. Update Instance's freshness status
    instance = await session.get(DatasetInstance, run.dataset_instance_id)
    instance.freshness_status = "error"

    # 2. Update StatusStore
    await status_store.mark_run_error(
        resource_id=instance.resource_id,
        error_message=error_message,
    )

    # 3. Publish real-time status update
    await centrifugo.publish(
        channel=f"instance:{instance.resource_id}:status",
        data={"status": "error", "run_id": str(run.id), "error": error_message},
    )

    # 4. Emit failure activity
    await emit_activity("pipeline_run.failed", run.id, {"error": error_message})
```

## 9. Unit Tests

Test the following:
*   Upstream freshness check blocks when not ready
*   Run is created with correct status transitions
*   StatusStore is updated on completion
*   Staleness is propagated to downstream
*   Real-time updates are published
*   Activities are emitted at each transition

```bash
pytest libs/orchestration/tests/test_orchestration.py -v
```

## References

*   `libs/orchestration/run_service.py` - RunExecutionService
*   `libs/orchestration/lineage.py` - LineageResolver
*   `libs/orchestration/freshness.py` - FreshnessChecker
*   `libs/orchestration/status_store.py` - StatusStore
