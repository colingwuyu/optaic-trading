# Client Architecture Patterns

## Directory Structure

```
libs/sdk_py/optaic/
  client.py             # Composite sync/async clients
  exceptions.py         # Custom exceptions
  resources/
    signals.py          # Signal operations (sync)
    signals_async.py    # Signal operations (async)
    datasets.py
    portfolios.py
```

## Dataclass Models

SDK models are simple dataclasses with `from_dict` factory:

```python
from dataclasses import dataclass
from uuid import UUID
from datetime import datetime
from typing import Optional

@dataclass
class Signal:
    """SDK representation of a signal."""
    id: UUID
    resource_id: UUID
    name: str
    signal_type: str
    frequency: str
    lookback_days: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Signal":
        return cls(
            id=UUID(data["id"]),
            resource_id=UUID(data["resource_id"]),
            name=data["name"],
            signal_type=data["signal_type"],
            frequency=data["frequency"],
            lookback_days=data.get("lookback_days"),
        )
```

## Sync Mixin Pattern

Each resource type has a mixin class:

```python
from uuid import UUID
from typing import List, Optional

class SignalsMixin:
    """Mixin providing signal operations."""

    def list_signals(
        self,
        parent_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[Signal]:
        """List signals under a parent resource."""
        response = self._client.get(
            "/api/v1/signals",
            params={
                "parent_id": str(parent_id),
                "limit": limit,
                "offset": offset
            }
        )
        response.raise_for_status()
        return [Signal.from_dict(s) for s in response.json()["items"]]

    def get_signal(self, signal_id: UUID) -> Signal:
        """Get a single signal by ID."""
        response = self._client.get(f"/api/v1/signals/{signal_id}")
        response.raise_for_status()
        return Signal.from_dict(response.json())

    def create_signal(
        self,
        parent_id: UUID,
        name: str,
        signal_type: str,
        **kwargs
    ) -> Signal:
        """Create a new signal."""
        response = self._client.post(
            "/api/v1/signals",
            json={
                "parent_id": str(parent_id),
                "name": name,
                "signal_type": signal_type,
                **kwargs
            }
        )
        response.raise_for_status()
        return Signal.from_dict(response.json())
```

## Async Mixin Pattern

Mirror sync mixin with async/await:

```python
class AsyncSignalsMixin:
    """Async mixin providing signal operations."""

    async def list_signals(
        self,
        parent_id: UUID,
        limit: int = 100
    ) -> List[Signal]:
        response = await self._client.get(
            "/api/v1/signals",
            params={"parent_id": str(parent_id), "limit": limit}
        )
        response.raise_for_status()
        return [Signal.from_dict(s) for s in response.json()["items"]]

    async def get_signal(self, signal_id: UUID) -> Signal:
        response = await self._client.get(f"/api/v1/signals/{signal_id}")
        response.raise_for_status()
        return Signal.from_dict(response.json())
```

## Composite Client

Combine mixins into unified client:

```python
import httpx
from optaic.resources.signals import SignalsMixin, AsyncSignalsMixin
from optaic.resources.datasets import DatasetsMixin, AsyncDatasetsMixin

class OptAICClient(SignalsMixin, DatasetsMixin):
    """Synchronous OptAIC client."""

    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def close(self):
        self._client.close()


class AsyncOptAICClient(AsyncSignalsMixin, AsyncDatasetsMixin):
    """Asynchronous OptAIC client."""

    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def close(self):
        await self._client.aclose()
```

## Exception Hierarchy

```python
class OptAICError(Exception):
    """Base exception for all SDK errors."""
    pass

class AuthenticationError(OptAICError):
    """API key invalid or missing."""
    pass

class AuthorizationError(OptAICError):
    """User lacks permission for this operation."""
    pass

class NotFoundError(OptAICError):
    """Resource not found."""
    pass

class ValidationError(OptAICError):
    """Request validation failed."""
    def __init__(self, message: str, errors: list):
        super().__init__(message)
        self.errors = errors

class GuardrailsBlockedError(OptAICError):
    """Operation blocked by guardrails contract."""
    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report

class RateLimitError(OptAICError):
    """Rate limit exceeded."""
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after
```

## Error Handling in Methods

```python
def _handle_response(self, response):
    """Convert HTTP errors to SDK exceptions."""
    if response.status_code == 401:
        raise AuthenticationError("Invalid API key")
    if response.status_code == 403:
        raise AuthorizationError(response.json().get("detail", "Forbidden"))
    if response.status_code == 404:
        raise NotFoundError(response.json().get("detail", "Not found"))
    if response.status_code == 422:
        data = response.json()
        if "guardrails" in data:
            raise GuardrailsBlockedError(data["message"], data["report"])
        raise ValidationError(data.get("detail", "Validation failed"), data.get("errors", []))
    if response.status_code == 429:
        raise RateLimitError("Rate limited", int(response.headers.get("Retry-After", 60)))
    response.raise_for_status()
```
