# Service Layer Patterns

## Standard Service Structure

```python
# libs/core/domain/<domain>_service.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from libs.core.activity import record_activity_with_outbox, ActivityEnvelope
from libs.db.models.resource import Resource, ResourceType

class SignalService:
    """Signal CRUD with mandatory activity emission."""

    def __init__(self, session: AsyncSession, actor_id: UUID, tenant_id: UUID):
        self.session = session
        self.actor_id = actor_id
        self.tenant_id = tenant_id

    async def create(self, dto: SignalCreateDTO, parent_id: UUID) -> SignalReadDTO:
        """Create signal and emit activity."""
        # 1. Create resource entry
        resource = Resource(
            name=dto.name,
            resource_type=ResourceType.SIGNAL,
            parent_id=parent_id,
            tenant_id=self.tenant_id
        )
        self.session.add(resource)
        await self.session.flush()

        # 2. Create domain record
        signal = Signal(
            resource_id=resource.id,
            tenant_id=self.tenant_id,
            signal_type=dto.signal_type,
            frequency=dto.frequency,
            lookback_days=dto.lookback_days,
            config=dto.config
        )
        self.session.add(signal)
        await self.session.flush()

        # 3. Emit activity (REQUIRED)
        await record_activity_with_outbox(
            session=self.session,
            envelope=ActivityEnvelope(
                tenant_id=self.tenant_id,
                actor_principal_id=self.actor_id,
                resource_id=resource.id,
                resource_type="signal",
                action="signal.created",
                payload={
                    "signal_type": dto.signal_type,
                    "frequency": dto.frequency
                }
            )
        )

        return SignalReadDTO.model_validate(signal)

    async def update(self, signal_id: UUID, dto: SignalUpdateDTO) -> SignalReadDTO:
        """Update signal and emit activity."""
        signal = await self._get_or_404(signal_id)

        # Track changes
        changes = {}
        if dto.lookback_days is not None and dto.lookback_days != signal.lookback_days:
            changes["lookback_days"] = {"old": signal.lookback_days, "new": dto.lookback_days}
            signal.lookback_days = dto.lookback_days
        if dto.config is not None:
            changes["config"] = {"old": signal.config, "new": dto.config}
            signal.config = dto.config

        # Emit activity
        await record_activity_with_outbox(
            session=self.session,
            envelope=ActivityEnvelope(
                tenant_id=self.tenant_id,
                actor_principal_id=self.actor_id,
                resource_id=signal.resource_id,
                resource_type="signal",
                action="signal.updated",
                payload={"changes": changes}
            )
        )

        return SignalReadDTO.model_validate(signal)

    async def delete(self, signal_id: UUID) -> None:
        """Soft delete signal and emit activity."""
        signal = await self._get_or_404(signal_id)
        resource = await self._get_resource(signal.resource_id)

        resource.deleted_at = datetime.utcnow()

        await record_activity_with_outbox(
            session=self.session,
            envelope=ActivityEnvelope(
                tenant_id=self.tenant_id,
                actor_principal_id=self.actor_id,
                resource_id=signal.resource_id,
                resource_type="signal",
                action="signal.deleted",
                payload={}
            )
        )
```

## Using tx_activity Wrapper

```python
from libs.core.activity import tx_activity

async def create_with_tx(dto: SignalCreateDTO) -> Signal:
    async def domain_fn(session: AsyncSession) -> Signal:
        # Domain logic here
        signal = Signal(...)
        session.add(signal)
        return signal

    envelope = ActivityEnvelope(
        action="signal.created",
        ...
    )

    result, activity = await tx_activity(db, envelope, domain_fn)
    return result
```

## Guardrails Integration

```python
from optaic.guardrails import GuardrailsEngine

async def create_with_validation(self, dto: SignalCreateDTO) -> SignalReadDTO:
    # 1. Create resource
    signal = await self._create(dto)

    # 2. Validate via guardrails
    report = await GuardrailsEngine.validate_at_gate(
        session=self.session,
        resource_id=signal.resource_id,
        gate="create",
        context={"subspace": "staging"}
    )

    # 3. Block if failed in official
    if not report.ok and report.enforced_as == "block":
        raise GuardrailsBlocked(report)

    return signal
```

## Lazy Import Pattern

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import numpy as np

def compute_signal(data: "pd.DataFrame") -> "pd.Series":
    import pandas as pd  # Import at runtime
    import numpy as np

    # Heavy computation here
    return pd.Series(...)
```
