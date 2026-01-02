---
trigger: model_decision
description: Agent trigger: Load this file when extending the OptAIC Python SDK with new resource operations, client methods, or async patterns.
---

# SDK Extension Rules

Guide for extending the OptAIC Python SDK with new resource operations.

## 1. Client Architecture

Location: `libs/sdk_py/optaic/`
- `client.py` - Composite sync/async clients
- `exceptions.py` - Custom exceptions
- `resources/` - Resource-specific operations

## 2. Key Patterns

### Mixin-Based Composition
Each resource type is a mixin class. Composite client inherits all mixins.

### Dataclass Models
SDK models are simple dataclasses with `from_dict` factory method.

### Definition vs Instance Operations
- **Definitions**: Mostly read-only (list, get, get_version)
- **Instances**: Full CRUD + run submission

## 3. Long-Running Operations

Runs and backtests need polling helpers with timeout and status callbacks.

## 4. Lazy Import Rule

Heavy deps (pandas, numpy, pyarrow) must be lazy-loaded in method bodies:
`python
def upload_dataframe(self, dataset_id, df):
    try:
        import pandas as pd
        import pyarrow as pa
    except ImportError:
        raise ImportError("pip install optaic[data]")
`

## 5. Exception Hierarchy

- `OptAICError` (base)
- `AuthenticationError`, `AuthorizationError`
- `NotFoundError`, `ValidationError`
- `GuardrailsBlockedError` (includes ValidationReport)

## 6. References

See `.claude/skills/sdk-patterns/` for complete patterns:
- `SKILL.md` - Full SDK architecture
- `references/client-patterns.md` - Architecture, mixins, exceptions
- `references/resource-operations.md` - CRUD, versions, runs
- `references/async-patterns.md` - Long-running ops, uploads, streaming
