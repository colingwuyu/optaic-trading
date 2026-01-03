# Flow Execution Resource Pairing

Guide for pairing Flow Execution Resources with Instance resources.

## Core Concept: Flows vs Runs

| Concept | Type | Description |
|---------|------|-------------|
| **Flow Execution Resource** | Static | Prefect deployment created when Instance is created |
| **Run** | Dynamic | Activity/action of a Flow (created on each trigger) |

```
Instance = "What" (configuration + capability)
Flow = "How it executes" (Prefect deployment, static)
Run = "When it executed" (activity, dynamic, many per Flow)
```

## Instance Creation Flow

When creating an Instance, the service must also create Flow Execution Resources:

```python
async def create_dataset_instance(
    session: AsyncSession,
    actor: ActorContext,
    payload: CreateDatasetInstancePayload,
) -> DatasetInstance:
    # 1. Create Resource record
    resource = Resource(
        tenant_id=actor.tenant_id,
        type="DatasetInstance",
        parent_id=payload.parent_id,
        name=payload.name,
    )
    session.add(resource)
    await session.flush()

    # 2. Create extension table record
    instance = DatasetInstance(
        resource_id=resource.id,
        tenant_id=actor.tenant_id,
        definition_resource_id=payload.definition_id,
        config_json=payload.config,
    )
    session.add(instance)
    await session.flush()

    # 3. Create Prefect deployment for refresh flow
    deployment = await create_prefect_deployment(
        name=f"{resource.name}_refresh",
        flow_name="dataset_refresh",
        parameters={"dataset_id": str(resource.id)},
        schedule=payload.schedule,
    )
    instance.prefect_deployment_id = deployment.id

    # 4. Emit activity
    await emit_activity(
        action="dataset_instance.created",
        resource_id=resource.id,
        payload={"deployment_id": str(deployment.id)},
    )

    return instance
```

## Multi-Flow Instance (ModelInstance)

ModelInstance creates multiple flows:

```python
async def create_model_instance(
    session: AsyncSession,
    actor: ActorContext,
    payload: CreateModelInstancePayload,
) -> ModelInstance:
    # 1. Create Resource + extension table record
    # ...

    # 2. Create MLflow experiment for training
    experiment_id = mlflow.create_experiment(f"model_{resource.id}")
    instance.mlflow_experiment_id = experiment_id

    # 3. Create Prefect deployments for each flow type
    training_deployment = await create_prefect_deployment(
        name=f"{resource.name}_training",
        flow_name="model_training",
        parameters={"model_id": str(resource.id)},
    )
    instance.prefect_training_deployment_id = training_deployment.id

    inference_deployment = await create_prefect_deployment(
        name=f"{resource.name}_inference",
        flow_name="model_inference",
        parameters={"model_id": str(resource.id)},
    )
    instance.prefect_inference_deployment_id = inference_deployment.id

    monitoring_deployment = await create_prefect_deployment(
        name=f"{resource.name}_monitoring",
        flow_name="model_monitoring",
        parameters={"model_id": str(resource.id)},
    )
    instance.prefect_monitoring_deployment_id = monitoring_deployment.id

    # 4. Create EvidentlyAI project for monitoring
    evidently_project = evidently.create_project(f"model_{resource.id}")
    instance.evidently_project_id = evidently_project.id

    return instance
```

## Flow Status Tracking

Each flow tracks its own status independently:

```python
class FlowStatus(str, Enum):
    NOT_INITIALIZED = "not_initialized"  # Flow created but never run
    READY = "ready"                       # Last run succeeded, data fresh
    STALE = "stale"                       # Needs refresh
    RUNNING = "running"                   # Currently executing
    ERROR = "error"                       # Last run failed
```

Status is stored in the StatusStore:

```python
# libs/orchestration/status_store.py
class DatasetStatusRecord:
    resource_id: UUID           # Flow/Instance ID
    last_pipeline_run: datetime
    last_pipeline_status: str   # "running", "success", "error"
    last_data_date: Optional[date]
    source_delay_detected: bool
```

## Lineage Registration

When creating an Instance with upstream dependencies, register lineage edges:

```python
async def create_dataset_instance(...):
    # ... create instance ...

    # Register lineage edges (flow-to-flow dependencies)
    for upstream_ref in payload.upstream_refs:
        await lineage_resolver.add_lineage_edge(
            session=session,
            tenant_id=actor.tenant_id,
            upstream_id=upstream_ref.resource_id,
            downstream_id=resource.id,
            edge_kind="data_dependency",
        )
```

## Definition-Specified Flow Behavior

The Definition resource specifies what flows to create:

```python
# Definition.metadata_json
{
    "flow_specs": [
        {
            "flow_kind": "refresh",
            "flow_template": "dataset_refresh",
            "parameters_schema": {...}
        }
    ],
    "lineage_contracts": [...],
    "status_aggregation_contract": {
        "aggregation_method": "min_severity",
        "status_priority": ["ERROR", "STALE", "RUNNING", "READY"]
    }
}
```

## Real-Time Status Updates

Instance subscribes to flow status changes via Centrifugo:

```python
# On flow status change
await centrifugo.publish(
    channel=f"instance:{instance_id}:status",
    data={
        "flow_kind": "refresh",
        "old_status": "running",
        "new_status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
    }
)
```

Observers (UI, downstream flows) subscribe to receive updates:

```typescript
// Frontend subscription
centrifuge.subscribe(`instance:${instanceId}:status`, (msg) => {
    updateInstanceStatus(msg.data);
});
```

## Cleanup on Instance Deletion

When deleting an Instance, cleanup Flow Execution Resources:

```python
async def delete_dataset_instance(session, actor, instance_id):
    instance = await session.get(DatasetInstance, instance_id)

    # 1. Delete Prefect deployment
    if instance.prefect_deployment_id:
        await delete_prefect_deployment(instance.prefect_deployment_id)

    # 2. Remove lineage edges
    await lineage_resolver.remove_lineage_edges_for_resource(
        session, instance_id
    )

    # 3. Delete resource (cascades to extension table)
    await session.delete(instance.resource)
```
