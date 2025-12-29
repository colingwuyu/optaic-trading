---
trigger: model_decision
description: Agent trigger: Load this file when extending the OptAIC Python SDK with new resource operations, client methods, or async patterns.
---

# SDK Extension Rules

This document governs SDK extension development for `libs/sdk_py/optaic/`.

## 1. Client Architecture

Use mixin-based composition for resource clients:

```python
class OptAICClient(SignalsMixin, DatasetsMixin, RunsMixin):
    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.Client(base_url=base_url, ...)
```

Location: `libs/sdk_py/optaic/resources/`

## 2. Dataclass Models

SDK models use dataclasses with `from_dict` factory:

```python
@dataclass
class Signal:
    id: UUID
    name: str

    @classmethod
    def from_dict(cls, data: dict) -> "Signal":
        return cls(id=UUID(data["id"]), name=data["name"])
```

## 3. Definition vs Instance Operations

- **Definitions**: Read-only (list, get, get_version)
- **Instances**: Full CRUD + run submission

## 4. Long-Running Operations

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

## 5. Exception Hierarchy

```python
class OptAICError(Exception): pass
class AuthenticationError(OptAICError): pass
class AuthorizationError(OptAICError): pass
class NotFoundError(OptAICError): pass
class ValidationError(OptAICError): pass
class GuardrailsBlockedError(OptAICError):
    def __init__(self, message, report):
        self.report = report
```

## 6. Lazy Import Rule

Heavy deps in method bodies only:

```python
def upload_dataframe(self, dataset_id, df):
    try:
        import pandas as pd
        import pyarrow as pa
    except ImportError:
        raise ImportError("pip install optaic[data]")
```