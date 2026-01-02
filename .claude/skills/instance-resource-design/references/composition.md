# Dataset Composition Pattern

DatasetInstance composes Pipeline, Store, and Accessor into a unified data asset.

## Architecture

```
                    DatasetInstance
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
PipelineInstance    StoreInstance    AccessorInstance
        │                 │                 │
        ▼                 ▼                 ▼
  PipelineDef         StoreDef        AccessorDef
 (ETL logic)       (storage)       (read pattern)
```

## Why Composition?

Decouples concerns for maximum reusability:

| Component | Responsibility | Swappable? |
|-----------|---------------|------------|
| Pipeline | Data ingestion/transform | Yes - change data source |
| Store | Physical storage | Yes - Parquet vs SQLite |
| Accessor | Read pattern | Yes - Simple vs PIT |

## Implementation

### Extension Tables

```sql
-- Pipeline instance
CREATE TABLE pipeline_instances (
    resource_id UUID PRIMARY KEY REFERENCES resources(id),
    definition_resource_id UUID NOT NULL REFERENCES resources(id),
    definition_version_id UUID REFERENCES resource_versions(id),
    config_json JSONB,
    schedule_json JSONB,
    last_run_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) DEFAULT 'active'
);

-- Store instance
CREATE TABLE store_instances (
    resource_id UUID PRIMARY KEY REFERENCES resources(id),
    definition_resource_id UUID NOT NULL REFERENCES resources(id),
    config_json JSONB,
    physical_path VARCHAR(1024)  -- e.g., "s3://bucket/datasets/xyz/"
);

-- Accessor instance
CREATE TABLE accessor_instances (
    resource_id UUID PRIMARY KEY REFERENCES resources(id),
    definition_resource_id UUID NOT NULL REFERENCES resources(id),
    config_json JSONB
);

-- Dataset instance (composition)
CREATE TABLE dataset_instances (
    resource_id UUID PRIMARY KEY REFERENCES resources(id),
    pipeline_instance_id UUID NOT NULL REFERENCES resources(id),
    store_instance_id UUID NOT NULL REFERENCES resources(id),
    accessor_instance_id UUID NOT NULL REFERENCES resources(id),
    freshness_status VARCHAR(50) DEFAULT 'unknown',  -- fresh|stale|unknown
    last_data_date DATE,
    row_count BIGINT
);
```

### Creating a Composed Dataset

```python
async def create_dataset_instance(
    db: AsyncSession,
    actor: ActorContext,
    payload: DatasetInstanceCreate,
    guardrails: GuardrailsEngine,
) -> Resource:
    # 1. Validate all component definitions exist
    pipeline_def = await get_resource_or_404(db, actor.tenant_id, payload.pipeline_def_id)
    store_def = await get_resource_or_404(db, actor.tenant_id, payload.store_def_id)
    accessor_def = await get_resource_or_404(db, actor.tenant_id, payload.accessor_def_id)

    # 2. Validate compatibility rules
    # Pipeline output must be compatible with Store input
    # Store output must be compatible with Accessor input

    # 3. Create component instances
    pipeline_instance = await create_pipeline_instance(db, actor, pipeline_def, payload.pipeline_config)
    store_instance = await create_store_instance(db, actor, store_def, payload.store_config)
    accessor_instance = await create_accessor_instance(db, actor, accessor_def, payload.accessor_config)

    # 4. Create dataset instance (composition)
    dataset_id = uuid4()

    async def domain_fn(session: AsyncSession) -> Resource:
        resource = Resource(
            id=dataset_id,
            tenant_id=actor.tenant_id,
            type="DatasetInstance",
            parent_id=payload.project_id,
            name=payload.name,
            status="active",
        )
        session.add(resource)

        dataset_ext = DatasetInstance(
            resource_id=dataset_id,
            pipeline_instance_id=pipeline_instance.id,
            store_instance_id=store_instance.id,
            accessor_instance_id=accessor_instance.id,
            freshness_status="unknown",
        )
        session.add(dataset_ext)
        return resource

    # 5. Guardrails validation
    await guardrails.validate_at_gate(db, scope="dataset", ...)

    # 6. Activity emission
    envelope = ActivityEnvelope(
        action="dataset.created",
        resource_id=dataset_id,
        resource_type="DatasetInstance",
        payload={
            "pipeline_def": str(pipeline_def.id),
            "store_def": str(store_def.id),
            "accessor_def": str(accessor_def.id),
        }
    )

    return await tx_activity(db, envelope, domain_fn)
```

## Lineage Tracking

Track composition in `resource_edges`:

```sql
INSERT INTO resource_edges (tenant_id, src_resource_id, dst_resource_id, edge_type)
VALUES
    (tenant_id, dataset_id, pipeline_instance_id, 'composes'),
    (tenant_id, dataset_id, store_instance_id, 'composes'),
    (tenant_id, dataset_id, accessor_instance_id, 'composes');
```

Query lineage:

```python
async def get_dataset_components(db: AsyncSession, dataset_id: UUID) -> dict:
    edges = await db.scalars(
        select(ResourceEdge).where(
            ResourceEdge.src_resource_id == dataset_id,
            ResourceEdge.edge_type == "composes"
        )
    )
    return {edge.edge_type: edge.dst_resource_id for edge in edges}
```
