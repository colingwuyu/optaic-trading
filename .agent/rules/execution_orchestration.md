---
trigger: model_decision
description: Agent trigger: Load this file when implementing execution orchestration, Flow Execution Resources, Run management, lineage checking, or real-time status updates.
---

# Execution Orchestration Rules

Guide for implementing execution orchestration with Flow Execution Resources, Runs, and lineage.

## 1. Flow Execution vs Runs (CRITICAL)

| Concept | Type | Lifecycle | Example |
|---------|------|-----------|---------|
| Flow Execution Resource | Static | Created with Instance | Prefect Deployment |
| Run | Dynamic | Created each trigger | Prefect Flow Run |

```
Flow = "How it executes" (static capability, created once)
Run = "When it executed" (dynamic activity, many per Flow)
```

## 2. Instance Creation Initializes Flows

When creating ANY Instance, MUST also create Flow Execution Resources:

```python
async def create_dataset_instance(session, actor, payload):
    # 1. Create Resource + extension table
    instance = ...

    # 2. Create Prefect deployment for refresh flow
    deployment = await create_prefect_deployment(
        name=f"{resource.name}_refresh",
        flow_name="dataset_refresh",
        parameters={"dataset_id": str(resource.id)},
        schedule=payload.schedule,
    )

    # 3. Store deployment ID in extension table
    instance.prefect_deployment_id = deployment.id
```

## 3. Lineage is Flow-to-Flow

Dependencies track flow statuses, NOT instance relationships:

```
DatasetInstance.refresh_flow
        ↓ depends on
UpstreamDataset.refresh_flow status = READY
```

## 4. Lineage Check Before Execution

```python
from libs.orchestration import (
    LineageResolver, FreshnessChecker, UpstreamNotReadyError
)

async def trigger_run(session, resource_id, force=False):
    resolver = LineageResolver()
    checker = FreshnessChecker(status_store)

    report = await resolver.check_upstream_freshness(
        session, resource_id, checker
    )

    if not report.all_ready and not force:
        raise UpstreamNotReadyError(...)
```

## 5. Status Aggregation

Instance status aggregates from its Flow(s):

```python
# Single-flow Instance
instance.status = flow.status

# Multi-flow Instance (ModelInstance)
instance.status = aggregate([
    training_flow.status,
    inference_flow.status,
    monitoring_flow.status,
])
```

## 6. DatasetStatus Enum

```python
NOT_INITIALIZED  # No data exists yet
READY            # Current and valid
STALE            # Outdated, needs refresh
STALE_SOURCE_DELAYED  # Source has no new data
ERROR            # Pipeline failed
```

## 7. Real-Time Status Updates

On status change, publish to Centrifugo:

```python
await centrifugo.publish(
    channel=f"instance:{instance_id}:status",
    data={"status": "ready", "last_run_id": str(run.id)}
)
```

## 8. Run Completion Updates Flow Status

```python
async def _on_run_completed(session, run):
    # 1. Update Instance's freshness status
    instance.freshness_status = "ready"

    # 2. Update StatusStore for freshness calculations
    await status_store.mark_run_success(...)

    # 3. Propagate staleness to downstream
    await lineage_resolver.propagate_staleness(session, instance_id)

    # 4. Publish real-time status update
    await centrifugo.publish(...)
```

## 9. Multi-Flow Instance Types

| Instance | Flows | Handles |
|----------|-------|---------|
| DatasetInstance | 1 (refresh) | prefect_deployment_id |
| ExperimentInstance | 1 (preview) | prefect_deployment_id |
| ModelInstance | 3 (train/infer/monitor) | 3 deployment IDs + mlflow_experiment_id + evidently_project_id |
| BacktestInstance | 1 (backtest) | prefect_deployment_id |

## 10. References

See `.claude/skills/` for complete patterns:
- `instance-resource-design/references/flow-pairing.md` - Flow pairing
- `run-resource-design/SKILL.md` - Run design patterns
- `data-pipeline-patterns/references/lineage-patterns.md` - Lineage patterns
