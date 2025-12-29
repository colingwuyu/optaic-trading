---
name: quant-resource-patterns
description: Follow these patterns when implementing quant domain resources like Dataset, Signal, Alpha, Portfolio, Strategy, Universe, or Backtest in OptAIC. Use for creating DB models, DTOs, services, and tests for trading-specific entities.
---

# Quant Resource Implementation Patterns

Guide for implementing domain resources that integrate with OptAIC's resource-based architecture.

## When to Use

Apply when:
- Creating new domain resource types (Dataset, Signal, Portfolio, etc.)
- Implementing Definition resources (plugins like PipelineDef, StoreDef)
- Implementing Instance resources (configured usages like DatasetInstance)
- Adding domain-specific DB models, DTOs, or services

## Two-Tier Resource Model

OptAIC separates **Definitions** (plugins) from **Instances** (configs):

```
Definition (Plugin)         Instance (Config)              Run (Execution)
─────────────────          ──────────────────             ────────────────
BloombergPipelineDef   →   SPX_OHLCV_Dataset          →   Daily refresh run
  (code + interface)         (config + refs)               (execution + version)
```

**Definitions**: Reusable building blocks submitted as plugins
**Instances**: Concrete configurations referencing definitions
**Runs**: Executions that produce immutable versions

## Implementation Workflow

### 1. Determine Resource Tier

**Definition resource?** → Implements abstract interface, has test suite, requires evaluation
**Instance resource?** → References definition(s), has config, can be scheduled

### 2. Create DB Model

Location: `libs/db/models/<domain>.py`

Link to resources table via FK. See [references/db-patterns.md](references/db-patterns.md).

### 3. Create DTOs

Location: `libs/core/domain/<domain>.py`

Use Pydantic. Never expose SQLAlchemy models to API. See [references/dto-patterns.md](references/dto-patterns.md).

### 4. Create Service Layer

Location: `libs/core/domain/<domain>_service.py`

Emit activities for all mutations. See [references/service-patterns.md](references/service-patterns.md).

### 5. Register ResourceType

Update `libs/core/resources.py` → `ResourceType` enum.

### 6. Generate Migration

```bash
optaic db revision --autogenerate -m "add <domain> resource"
```

### 7. Write Tests

Location: `libs/core/tests/test_<domain>.py`

## Critical Rules

1. **Lazy imports** - Heavy deps (pandas, numpy, torch) must use `TYPE_CHECKING` blocks
2. **Activity emission** - All mutations emit activities in service layer
3. **Guardrails hooks** - Validate at lifecycle gates (create/update/promote)
4. **Version tracking** - Instances reference definition versions

## Reference Files

- [DB Model Patterns](references/db-patterns.md) - SQLAlchemy patterns
- [DTO Patterns](references/dto-patterns.md) - Pydantic schemas
- [Service Patterns](references/service-patterns.md) - CRUD with activities
