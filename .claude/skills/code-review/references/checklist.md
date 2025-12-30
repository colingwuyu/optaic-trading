# Code Review Checklist by Component Type

## Quick Reference: Files to Check by Location

| Path Pattern | Component Type | Key Checks |
|--------------|----------------|------------|
| `libs/core/domain/*_service.py` | Service | Activity, Guardrails |
| `libs/core/domain/*.py` (DTOs) | DTO | Pydantic, No SQLAlchemy |
| `libs/db/models/*.py` | DB Model | Base class, FK, Migration |
| `apps/api/routers/*.py` | API Handler | Returns DTO, No activity |
| `libs/sdk_py/**/*.py` | SDK | Lazy imports, from_dict |
| `libs/core/pipelines/*.py` | Pipeline | PIT, Arrow schema |

---

## Service Layer Components

### Required Patterns
- [ ] Inherits from or follows base service structure
- [ ] Constructor takes `session`, `actor_id`, `tenant_id`
- [ ] All CRUD methods emit ActivityEnvelope
- [ ] Uses `record_activity_with_outbox()` or `tx_activity()`
- [ ] Activity action follows `<resource>.<verb>` naming
- [ ] Guardrails validation at create/update
- [ ] Returns DTOs, not SQLAlchemy models
- [ ] Async methods for all DB operations

### Activity Emission Check
```python
# REQUIRED for every mutation
await record_activity_with_outbox(
    session=self.session,
    envelope=ActivityEnvelope(
        tenant_id=self.tenant_id,
        actor_principal_id=self.actor_id,
        resource_id=resource.id,
        resource_type="<type>",
        action="<type>.created|updated|deleted",
        payload={...}
    )
)
```

### Common Mutation Actions
| Operation | Action Name |
|-----------|-------------|
| Create | `<resource>.created` |
| Update | `<resource>.updated` |
| Delete | `<resource>.deleted` |
| Execute/Run | `<resource>.executed` |
| Promote | `<resource>.promoted` |
| Share | `<resource>.shared` |

---

## Database Model Components

### Required Patterns
- [ ] Inherits from shared `Base` class
- [ ] Location: `libs/db/models/`
- [ ] FK to `resources.id` if top-level entity
- [ ] ResourceType enum updated
- [ ] Alembic migration generated

---

## DTO Components

### Required Patterns
- [ ] Uses Pydantic `BaseModel`
- [ ] Location: `libs/core/domain/`
- [ ] No SQLAlchemy imports
- [ ] No vendor-specific types in fields
- [ ] Separate Create/Update/Read DTOs

---

## Pipeline/Data Components

### Required Patterns
- [ ] Arrow schema defined with `knowledge_date` field
- [ ] PIT query pattern used (both as_of_date AND knowledge_date)
- [ ] Data quality checks implemented
- [ ] Activity emitted on data refresh

### PIT Query Check
```python
# CORRECT pattern
WHERE as_of_date <= :target_date
  AND knowledge_date <= :knowledge_cutoff
ORDER BY knowledge_date DESC
```

---

## SDK Client Components

### Required Patterns
- [ ] Mixin-based composition
- [ ] Dataclass models with `from_dict()`
- [ ] Heavy deps imported in method bodies
- [ ] Exception hierarchy respected
- [ ] Async/sync parity maintained

---

## Two-Tier Resource Model

### Definitions (Abstract, Versioned)
- [ ] Implements required abstract interface
- [ ] Contains test suite
- [ ] Versioned independently
- [ ] Location: appropriate `*Def` model

### Instances (Config-as-Code)
- [ ] References `(def_resource_id, def_version_id)`
- [ ] Config stored as JSON/dict
- [ ] Immutable once promoted

### Runs (Executions)
- [ ] Produces immutable versions
- [ ] Creates lineage edges
- [ ] Emits execution activities

---

## API Handler Components

### Required Patterns
- [ ] Returns Pydantic DTOs (NOT SQLAlchemy models)
- [ ] Does NOT emit activities (service layer does this)
- [ ] Uses dependency injection for services
- [ ] Proper HTTP status codes
- [ ] Request validation via Pydantic

### Anti-Pattern Check
```python
# WRONG - Don't do this in API handlers
@router.post("/signals")
async def create_signal(dto):
    signal = await service.create(dto)
    await record_activity(...)  # ❌ Should be in service
    return signal  # ❌ Should return DTO
```

---

## Resource Hierarchy

### Standard Hierarchy
```
Tenant
└── Space (Personal/Team/System)
    └── Subspace (official/staging)
        └── Project
            └── Resource (Dataset, Signal, etc.)
                └── ResourceVersion
```

### Required FK Relationships
- [ ] `parent_id` → parent resource
- [ ] `space_id` → containing space
- [ ] `tenant_id` → tenant isolation
