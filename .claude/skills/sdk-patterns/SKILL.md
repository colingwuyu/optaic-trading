---
name: sdk-patterns
description: Follow these patterns when extending the OptAIC Python SDK with new domain operations. Use for adding client methods for datasets, signals, portfolios, backtests, and other resources. Covers async/sync interfaces, uploads, and long-running operations.
---

# SDK Extension Patterns

Guide for extending the OptAIC Python SDK with new resource operations.

## When to Use

Apply when:
- Adding new resource type operations to the SDK
- Implementing Definition or Instance client methods
- Adding upload/download capabilities
- Creating long-running operation helpers

## Client Architecture

```
libs/sdk_py/optaic/
  client.py             # Composite sync/async clients
  exceptions.py         # Custom exceptions
  resources/
    signals.py          # Signal operations (sync)
    signals_async.py    # Signal operations (async)
    datasets.py
```

See [references/client-patterns.md](references/client-patterns.md).

## Key Patterns

### Mixin-Based Composition
Each resource type is a mixin class. Composite client inherits all mixins:

```python
class OptAICClient(SignalsMixin, DatasetsMixin, RunsMixin):
    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.Client(base_url=base_url, ...)
```

### Dataclass Models
SDK models are simple dataclasses with `from_dict` factory:

```python
@dataclass
class Signal:
    id: UUID
    name: str

    @classmethod
    def from_dict(cls, data: dict) -> "Signal":
        return cls(id=UUID(data["id"]), name=data["name"])
```

### Definition vs Instance Operations
- **Definitions**: Mostly read-only (list, get, get_version)
- **Instances**: Full CRUD + run submission

See [references/resource-operations.md](references/resource-operations.md).

## Long-Running Operations

Runs and backtests need polling helpers:

```python
def run_and_wait(
    self,
    instance_id: UUID,
    timeout: float = 3600,
    on_status: Optional[Callable] = None
) -> Run:
    run = self.submit_run(instance_id)
    while run.status not in ("completed", "failed"):
        run = self.get_run(run.id)
        if on_status:
            on_status(run)
        time.sleep(5.0)
    return run
```

See [references/async-patterns.md](references/async-patterns.md).

## Upload with Progress

```python
def upload_dataframe(self, dataset_id: UUID, df, on_progress=None):
    import pyarrow.parquet as pq
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(df), buffer)
    buffer.seek(0)
    return self._upload(dataset_id, buffer, on_progress)
```

## Lazy Import Rule

Heavy deps must be lazy-loaded in method bodies:

```python
def upload_dataframe(self, dataset_id, df):
    try:
        import pandas as pd
        import pyarrow as pa
    except ImportError:
        raise ImportError("pip install optaic[data]")
```

## Exception Hierarchy

```python
class OptAICError(Exception): pass
class AuthenticationError(OptAICError): pass
class AuthorizationError(OptAICError): pass
class NotFoundError(OptAICError): pass
class ValidationError(OptAICError): pass
class GuardrailsBlockedError(OptAICError):
    def __init__(self, message, report):
        self.report = report  # ValidationReport for user inspection
```

## Reference Files

- [Client Patterns](references/client-patterns.md) - Architecture, mixins, exceptions
- [Resource Operations](references/resource-operations.md) - CRUD, versions, runs
- [Async Patterns](references/async-patterns.md) - Long-running ops, uploads, streaming
