---
trigger: model_decision
description: Agent trigger: Load this file when extending the OptAIC Python SDK with new resource operations, client methods, or async patterns.
---

# SDK Extension Rules

Guide for extending the OptAIC Python SDK with new resource operations.

## 1. Client Architecture

Location: `libs/sdk_py/`
- `client.py` - Main client with AuthClient, TenantsClient, ResourcesClient
- `admin.py` - AdminClient (user/space creation)
- `ops.py` - OpsClient (operators, expressions)

## 2. Authentication

The SDK supports multiple authentication methods:

```python
# API Key authentication (production)
client = AsyncPlatformClient(
    base_url="http://localhost:8081",
    api_key="optaic_xxx.secret",
)

# Dev mode authentication (testing)
client = AsyncPlatformClient(base_url="http://localhost:8081")
client.set_principal_id(principal_id)
client.set_tenant_id(tenant_id)
```

AuthClient provides API key management:
- `auth.create_api_key(name, ...)` - Create new key (returns full key once)
- `auth.list_api_keys()` - List keys for principal
- `auth.revoke_api_key(key_id)` - Revoke a key
- `auth.get_current_user()` - Get authenticated user info

## 3. Key Patterns

### Mixin-Based Composition
Each resource type is a mixin class. Composite client inherits all mixins.

### Dataclass Models
SDK models are simple dataclasses with `from_dict` factory method.

### Definition vs Instance Operations
- **Definitions**: Mostly read-only (list, get, get_version)
- **Instances**: Full CRUD + run submission

## 4. Long-Running Operations

Runs and backtests need polling helpers with timeout and status callbacks.

## 5. Lazy Import Rule

Heavy deps (pandas, numpy, pyarrow) must be lazy-loaded in method bodies:
```python
def upload_dataframe(self, dataset_id, df):
    try:
        import pandas as pd
        import pyarrow as pa
    except ImportError:
        raise ImportError("pip install optaic[data]")
```

## 6. Exception Hierarchy

- `OptAICError` (base)
- `AuthenticationError`, `AuthorizationError`
- `NotFoundError`, `ValidationError`
- `GuardrailsBlockedError` (includes ValidationReport)

## 7. References

See `.claude/skills/sdk-patterns/` for complete patterns:
- `SKILL.md` - Full SDK architecture (includes auth patterns)
- `references/client-patterns.md` - Architecture, mixins, exceptions
- `references/resource-operations.md` - CRUD, versions, runs
- `references/async-patterns.md` - Long-running ops, uploads, streaming
