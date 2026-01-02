# Migration Code Examples

Before/after patterns for porting optaic-v0 code.

## Example 1: Dataset Preview

### Before (optaic-v0)
```python
class DataAPI:
    def preview(self, name: str, start_date=None, end_date=None) -> pd.DataFrame:
        info = DATA_CATALOG.get(name)
        if not check_permission(self.user, "read", name):
            raise PermissionError("Access denied")

        accessor = ACCESSOR_FACTORY[info.accessor_type](info)
        data = accessor.read(start_date, end_date)

        audit_operation("dataset.preview", self.user, name, {
            "start_date": start_date,
            "end_date": end_date
        })
        return data
```

### After (optaic-trading)
```python
class DatasetService:
    async def preview(
        self,
        db: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DataPreviewOut:
        # 1. Get resource with tenant isolation
        resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)

        # 2. RBAC check
        await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

        # 3. Load instance extension
        instance = await db.scalar(
            select(DatasetInstance).where(DatasetInstance.resource_id == dataset_id)
        )

        # 4. Load accessor from definition
        accessor_def = await get_resource_or_404(
            db, actor.tenant_id, instance.accessor_instance_id
        )
        accessor = await self.load_accessor(accessor_def)

        # 5. Read data
        data = await accessor.read(start_date, end_date)

        # 6. Emit activity
        await record_activity_with_outbox(
            db,
            ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=dataset_id,
                resource_type="dataset",
                action="dataset.previewed",
                payload={"start_date": str(start_date), "end_date": str(end_date)},
            )
        )

        # 7. Return DTO (never raw DataFrame)
        return DataPreviewOut(
            columns=list(data.columns),
            rows=data.to_dict(orient="records")[:100],
            total_rows=len(data),
        )
```

## Example 2: Expression Evaluation

### Before (optaic-v0)
```python
def evaluate_expression(expr: str, datasets: dict[str, str]) -> pd.DataFrame:
    parsed = parse_expression(expr)
    inputs = {alias: DATA_CATALOG.get(name) for alias, name in datasets.items()}
    result = ExpressionEngine.evaluate(parsed, inputs)
    return result
```

### After (optaic-trading)
```python
class OpService:
    async def evaluate(
        self,
        db: AsyncSession,
        actor: ActorContext,
        request: ExpressionEvalRequest,
    ) -> ExpressionEvalOut:
        # 1. Parse expression
        parsed = parse_expression(request.expression)

        # 2. Resolve dataset references (with RBAC)
        inputs = {}
        for alias, dataset_id in request.datasets.items():
            resource = await get_resource_or_404(db, actor.tenant_id, dataset_id)
            await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)
            inputs[alias] = await self.load_dataset(db, resource)

        # 3. Evaluate
        result = await self.expression_engine.evaluate(parsed, inputs)

        # 4. Activity emission
        await record_activity_with_outbox(
            db,
            ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=None,  # Ephemeral operation
                resource_type="expression",
                action="expression.evaluated",
                payload={"expression": request.expression},
            )
        )

        return ExpressionEvalOut(result=result.to_dict(orient="records"))
```

## Example 3: Pipeline Registration

### Before (optaic-v0)
```python
PIPELINE_FACTORY["bloomberg"] = BloombergPipeline
PIPELINE_FACTORY["fred"] = FREDPipeline

def register_pipeline(name: str, cls: type):
    PIPELINE_FACTORY[name] = cls
```

### After (optaic-trading)
```python
# Pipelines are now resources, not in-memory registry

async def submit_pipeline_definition(
    db: AsyncSession,
    actor: ActorContext,
    payload: PipelineDefCreate,
    guardrails: GuardrailsEngine,
) -> ResourceOut:
    # Create as Resource
    resource_id = uuid4()

    async def domain_fn(session: AsyncSession) -> Resource:
        resource = Resource(
            id=resource_id,
            tenant_id=actor.tenant_id,
            type="PipelineDef",
            name=payload.name,
            owner_principal_id=actor.id,
            status="draft",
        )
        session.add(resource)

        # Extension table
        pipeline_def = PipelineDefinition(
            resource_id=resource_id,
            category=payload.category,
            code_ref=payload.code_ref,
            parameters_schema=payload.parameters_schema,
        )
        session.add(pipeline_def)
        return resource

    # Guardrails validation
    await guardrails.validate_at_gate(
        db=db,
        scope="pipeline_def",
        target_id=str(resource_id),
        context=GuardrailsContext(...),
        target_snapshot=payload.model_dump(),
    )

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type="PipelineDef",
        action="pipeline_def.submitted",
        payload={"name": payload.name, "category": payload.category},
    )

    resource, _ = await tx_activity(db, envelope, domain_fn)
    return ResourceOut.model_validate(resource)
```

## Example 4: code_ref Linkage (DatasetInstance Execution)

The key integration pattern bridging DB models to Factory execution:

### Before (optaic-v0)
```python
# Direct factory lookup by name
info = DATA_CATALOG.get(dataset_name)
pipeline = PIPELINE_FACTORY[info.source_type]
store = STORE_FACTORY[info.backend_type](info.physical_path)
accessor = ACCESSOR_FACTORY[info.accessor_type](store, info)
data = accessor.read(start_date, end_date)
```

### After (optaic-trading)
```python
class DatasetService:
    async def preview_dataset(self, session, actor, dataset_id: UUID, *, as_of_date=None):
        # 1. Load DatasetInstance resource + extension
        instance = await session.get(DatasetInstance, dataset_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"DatasetInstance {dataset_id} not found")

        # 2. Load component instances (composition pattern)
        store_inst = await session.get(StoreInstance, instance.store_instance_id)
        accessor_inst = await session.get(AccessorInstance, instance.accessor_instance_id)

        # 3. Load component definitions (to get code_ref)
        store_def = await session.get(StoreDefinition, store_inst.definition_resource_id)
        accessor_def = await session.get(AccessorDefinition, accessor_inst.definition_resource_id)

        # 4. Build execution objects from factories using code_ref
        store = STORE_FACTORY.build(
            store_def.code_ref,          # "ParquetStore" → ParquetStore class
            resource_id=str(store_inst.resource_id),
            config=store_inst.config_json or {},
            data_dir=self.data_dir,
        )
        accessor = ACCESSOR_FACTORY.build(
            accessor_def.code_ref,       # "PITAccessor" → PITAccessor class
            resource_id=str(accessor_inst.resource_id),
            config=accessor_inst.config_json or {},
            store=store,
        )

        # 5. Execute
        df = accessor.get(as_of_date=as_of_date)

        # 6. Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=dataset_id,
            resource_type="DatasetInstance",
            action="dataset.previewed",
            payload={"as_of_date": str(as_of_date) if as_of_date else None},
        )
        await record_activity_with_outbox(session, envelope)

        # 7. Return response (convert DataFrame to dict)
        return self._dataframe_to_response(df, instance)
```

### Key Insight: Two-Table Pattern

Every quant resource uses:
1. **Resource table**: governance (RBAC, versioning, activity, hierarchy)
2. **Extension table**: domain data (code_ref, config, metrics)

The `code_ref` field in Definition extension tables links to factory registration keys.

## Key Transformation Patterns

| Pattern | optaic-v0 | optaic-trading |
|---------|-----------|----------------|
| Identity | `user` string | `ActorContext` with tenant/principal |
| Lookup | `CATALOG[name]` | `get_resource_or_404(db, tenant_id, uuid)` |
| Permission | `check_permission()` | `authorize_or_403()` |
| Audit | `audit_operation()` | `record_activity_with_outbox()` |
| Return | `pd.DataFrame` | Pydantic DTO |
| Mutation | Direct dict update | `tx_activity()` wrapper |
| Error | `raise Exception` | `raise HTTPException(status_code=...)` |
| Factory | `FACTORY[name]` | `Def.code_ref` → `FACTORY.build(code_ref)` |
