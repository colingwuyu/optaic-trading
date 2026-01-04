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

## 3. Lineage DAG at Flow Creation (NOT Execution)

**CRITICAL**: Lineage DAG is built when Instances are CREATED, NOT at execution time.

This is the correct architecture:
- Build DAG at creation time
- Create subscriptions for pub/sub pattern
- Cache upstream IDs for fast execution checks

```python
from libs.orchestration import LineageResolver

# At DatasetInstance creation:
async def create_dataset_instance(session, actor, payload):
    # 1. Create Resource + extension
    instance = ...

    # 2. Build lineage DAG from pipeline config (CREATION TIME)
    resolver = LineageResolver()
    dag = await resolver.build_dag_for_instance(session, instance.id, actor.tenant_id)

    # 3. Cache upstream IDs for fast execution checks
    if dag.has_dependencies:
        instance.upstream_resource_ids = dag.upstream_ids
        instance.upstream_status = {str(uid): "unknown" for uid in dag.upstream_ids}

        # 4. Create DatasetLineage + Subscription records (pub/sub)
        await resolver.create_lineage_and_subscriptions(session, dag)
```

## 4. Pub/Sub Observer Pattern

Downstreams subscribe to upstream completion events:

```python
from libs.orchestration import LineageObserver, CentrifugoNotifier

# In PipelineRunService._on_run_completed:
async def _on_run_completed(session, run):
    # 1. Notify downstream dependents via observer
    observer = LineageObserver()
    ready_ids = await observer.on_upstream_completed(
        session,
        upstream_id=run.dataset_instance_id,
        run_id=run.resource_id,
    )

    # 2. Publish real-time notifications to Centrifugo
    notifier = CentrifugoNotifier()
    for downstream_id in ready_ids:
        await notifier.notify_upstream_ready(downstream_id, upstream_id, all_ready=True)
```

Observer methods:
- `on_upstream_completed()` - Marks upstream as "ready" in downstreams
- `on_upstream_failed()` - Marks upstream as "error" in downstreams
- `on_upstream_started()` - Marks upstream as "running" in downstreams
- `get_ready_to_run()` - Gets all datasets with all upstreams ready

## 5. Execution Check (From Cached Status)

Fast execution check uses cached upstream_status, NOT full lineage query:

```python
from libs.orchestration import LineageResolver

resolver = LineageResolver()
all_ready = await resolver.check_all_upstreams_ready(session, instance_id)

if not all_ready and not force:
    raise UpstreamNotReadyError(...)
```

## 6. Status Aggregation

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

## 7. DatasetStatus Enum

```python
NOT_INITIALIZED  # No data exists yet
READY            # Current and valid
STALE            # Outdated, needs refresh
STALE_SOURCE_DELAYED  # Source has no new data
ERROR            # Pipeline failed
```

## 8. Real-Time Status Updates

On status change, publish to Centrifugo:

```python
await centrifugo.publish(
    channel=f"instance:{instance_id}:status",
    data={"status": "ready", "last_run_id": str(run.id)}
)
```

## 9. Run Completion Updates Flow Status

```python
async def _on_run_completed(session, run):
    # 1. Update Instance's freshness status
    instance.freshness_status = "ready"

    # 2. Update StatusStore for freshness calculations
    await status_store.mark_run_success(...)

    # 3. Notify downstream dependents via observer pattern
    observer = LineageObserver()
    ready_ids = await observer.on_upstream_completed(session, instance_id, run.id)

    # 4. Publish real-time status updates
    notifier = CentrifugoNotifier()
    for downstream_id in ready_ids:
        await notifier.notify_upstream_ready(downstream_id, instance_id, True)
```

## 10. Schedule Management

Datasets can have scheduled refresh:

```python
# GET /datasets/{id}/schedule - Get schedule config
# PUT /datasets/{id}/schedule - Update schedule
# DELETE /datasets/{id}/schedule - Remove schedule

# Schedule syncs to Prefect deployment
await orchestrator.update_schedule(
    deployment_id=instance.prefect_deployment_id,
    schedule={"cron": "0 6 * * *"},  # 6am daily
)
```

## 11. Multi-Flow Instance Types

| Instance | Flows | Handles |
|----------|-------|---------|
| DatasetInstance | 1 (refresh) | prefect_deployment_id |
| ExperimentInstance | 1 (preview) | prefect_deployment_id |
| ModelInstance | 3 (train/infer/monitor) | 3 deployment IDs + mlflow_experiment_id + evidently_project_id |
| BacktestInstance | 1 (backtest) | prefect_deployment_id |

## 12. References

See `.claude/skills/` for complete patterns:
- `instance-resource-design/references/flow-pairing.md` - Flow pairing
- `run-resource-design/SKILL.md` - Run design patterns
- `data-pipeline-patterns/references/lineage-patterns.md` - Lineage patterns
