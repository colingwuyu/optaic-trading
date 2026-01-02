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
