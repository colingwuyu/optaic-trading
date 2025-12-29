---
trigger: model_decision
description: Agent trigger: Load this file when implementing new domain logic, resources, or DB models.
---

# Domain Logic & Resource Implementation Rules

This document governs how to add new business objects (Resources) and domain logic to the OptAIC platform.

## 1. Database Model Implementation

*   **Location**: All database models must reside in `libs/db/models/`.
*   **Inheritance**: Models must inherit from the shared `Base` class.
*   **Resource Link**: If the object is a top-level entity managed by the platform, it MUST link to the `resources` table.
    *   It should likely act as a specific "Type" of resource defined in the `ResourceType` enum.
    *   It should have a foreign key to `resources.id` if it extends the base Resource concept.
*   **Migrations**: Always generate an Alembic migration for schema changes.
    *   Command: `optaic db revision --autogenerate -m "add <model_name>"`

## 2. Service Layer & DTOs

*   **Location**: Service logic and DTOs should generally live in `libs/core` or `libs/domain` (if created).
*   **DTOs**: Use Pydantic BaseModel for data transfer objects.
    *   Do NOT expose raw SQLAlchemy models to the API layer.
    *   DTOs must be "adapter-friendly" (avoid vendor-specific types in the public interface).
*   **Dependencies**:
    *   **Core Rule**: `libs/core` and `libs/db` must remain lightweight.
    *   **Heavy Libs**: Do NOT import pandas, numpy, torch, mlflow, or prefect at the top level in core modules.
    *   **Lazy Loading**: Use `TYPE_CHECKING` blocks or local imports for heavy dependencies.

## 3. Resource Registration

*   **Enum**: Add the new resource type string to `libs/core/resources.py` -> `ResourceType`.
*   **Factory**: If there's a resource factory or polymorphic loader, update it to handle the new type.

## 4. Testing

*   **Unit Tests**: Required for all new logic.
*   **Pattern**:
    *   Test DTO serialization/deserialization.
    *   Test DB model constraints (integrity).
    *   Test service methods (mocking DB session where appropriate).

## 5. Directory Structure Reference

```text
optaic-trading/
 libs/
    db/
       models/       <-- New DB Tables
    core/             <-- New DTOs and Logic
 apps/
    api/              <-- API Endpoints (FastAPI)
    worker/           <-- Background Tasks
```
## 6. Two-Tier Resource Model (Quant Domain)

OptAIC separates **Definitions** (plugins) from **Instances** (configs):

```
Definition (Plugin)         Instance (Config)              Run (Execution)
─────────────────          ──────────────────             ────────────────
BloombergPipelineDef   →   SPX_OHLCV_Dataset          →   Daily refresh run
  (code + interface)         (config + refs)               (execution + version)
```

- **Definitions**: Reusable building blocks submitted as plugins
- **Instances**: Concrete configurations referencing definitions
- **Runs**: Executions that produce immutable versions

## 7. Activity Emission

**Core rule**: If it changes state, it MUST emit an activity.

All mutations emit activities in the **service layer** (not API handlers):

```python
await record_activity_with_outbox(
    session=self.session,
    envelope=ActivityEnvelope(
        action="signal.created",
        actor_principal_id=self.actor_id,
        resource_id=resource.id,
        resource_type="signal",
        payload={"signal_type": dto.signal_type}
    )
)
```

## 8. Guardrails Hooks

Validate at lifecycle gates:
- `resource.create` / `resource.update`
- `promotion.request` / `promotion.merge`
- `run.submit` / `run.start`

## 9. Version Tracking

Instances must reference definition versions for reproducibility:

```python
class DatasetInstance:
    pipeline_def_id: UUID
    pipeline_def_version: int  # Pinned version
```
