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
libs/sdk_py/
  __init__.py           # Exports AsyncPlatformClient + domain clients
  client.py             # Main client with lazy-loaded domain properties
  ops.py                # OpsClient (operators, expression evaluation)
  datasets.py           # DatasetsClient (preview, refresh, status)
  signals.py            # SignalsClient (register, validate, promote)
  pipelines.py          # PipelinesClient (definitions, instances, runs)
  experiments.py        # ExperimentsClient (create, run, save-as-macro)
  tests/
    test_sdk.py         # Unit tests for all clients
```

## Key Patterns

### Lazy-Loaded Domain Clients
Domain clients are properties that lazy-load on first access:

```python
class AsyncPlatformClient:
    def __init__(self, base_url: str, principal_id: str, tenant_id: str):
        self._client = httpx.AsyncClient(base_url=base_url)
        self._ops: OpsClient | None = None
        self._datasets: DatasetsClient | None = None

    @property
    def ops(self) -> OpsClient:
        if self._ops is None:
            from .ops import OpsClient
            self._ops = OpsClient(self)
        return self._ops

    @property
    def datasets(self) -> DatasetsClient:
        if self._datasets is None:
            from .datasets import DatasetsClient
            self._datasets = DatasetsClient(self)
        return self._datasets
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

## Domain Client Pattern

Each domain client follows a consistent pattern:

```python
class DatasetsClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def list(
        self,
        *,
        parent_id: Optional[str | UUID] = None,
        limit: int = 50,
        principal_id: Optional[str | UUID] = None,  # Per-call override
        tenant_id: Optional[str | UUID] = None,      # Per-call override
    ) -> list[Dict[str, Any]]:
        params = _drop_none({"parent_id": _to_str(parent_id), "limit": limit})
        return await self._client._request(
            "GET", "/datasets", params=params,
            principal_id=principal_id, tenant_id=tenant_id,
        )
```

### Helper Functions
Each client module includes:
```python
def _to_str(value: Optional[str | UUID]) -> Optional[str]:
    return str(value) if value else None

def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}
```

### Date Conversion
Methods accepting dates convert them to ISO strings:
```python
async def preview(
    self, dataset_id: UUID, *,
    start_date: Optional[date | str] = None,
    as_of_date: Optional[date | str] = None,
) -> Dict[str, Any]:
    def _date_str(d):
        return d.isoformat() if isinstance(d, date) else d
    payload = _drop_none({
        "start_date": _date_str(start_date),
        "as_of_date": _date_str(as_of_date),
    })
    return await self._client._request("POST", f"/datasets/{dataset_id}/preview", json=payload)
```

## API Endpoint Mapping

SDK methods map to REST API endpoints. See [docs/API_QUANT_REFERENCE.md](../../../docs/API_QUANT_REFERENCE.md).

| SDK Method | HTTP | Endpoint |
|------------|------|----------|
| `ops.list(category=None)` | GET | `/ops` |
| `ops.get(name)` | GET | `/ops/{name}` |
| `ops.evaluate(expr, context)` | POST | `/ops/evaluate` |
| `pipelines.list_definitions()` | GET | `/pipelines/definitions` |
| `pipelines.submit_definition(...)` | POST | `/pipelines/definitions` |
| `pipelines.deploy_definition(id)` | POST | `/pipelines/definitions/{id}/deploy` |
| `pipelines.list_instances()` | GET | `/pipelines/instances` |
| `pipelines.create_instance(...)` | POST | `/pipelines/instances` |
| `pipelines.run(id)` | POST | `/pipelines/instances/{id}/run` |
| `datasets.create(...)` | POST | `/datasets` |
| `datasets.list()` | GET | `/datasets` |
| `datasets.get(id)` | GET | `/datasets/{id}` |
| `datasets.status(id)` | GET | `/datasets/{id}/status` |
| `datasets.preview(id, ...)` | POST | `/datasets/{id}/preview` |
| `datasets.refresh(id)` | POST | `/datasets/{id}/refresh` |
| `signals.list()` | GET | `/signals` |
| `signals.register(...)` | POST | `/signals` |
| `signals.get(id)` | GET | `/signals/{id}` |
| `signals.validate(id)` | POST | `/signals/{id}/validate` |
| `signals.promote(id)` | POST | `/signals/{id}/promote` |
| `experiments.list()` | GET | `/experiments` |
| `experiments.create(...)` | POST | `/experiments` |
| `experiments.get(id)` | GET | `/experiments/{id}` |
| `experiments.run(id, ...)` | POST | `/experiments/{id}/run` |
| `experiments.update(id, ...)` | PATCH | `/experiments/{id}` |
| `experiments.save_as_macro(id)` | POST | `/experiments/{id}/save-as-macro` |

## Reference Files

- [Client Patterns](references/client-patterns.md) - Architecture, mixins, exceptions
- [Resource Operations](references/resource-operations.md) - CRUD, versions, runs
- [Async Patterns](references/async-patterns.md) - Long-running ops, uploads, streaming
