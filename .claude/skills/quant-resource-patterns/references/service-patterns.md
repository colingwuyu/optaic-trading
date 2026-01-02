# Service Layer Patterns

## code_ref Linkage Pattern (CRITICAL)

Services bridge the Resource model (governance) to Factory-based execution (domain logic):

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                 │
│                     (apps/api/services/)                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│ DatasetService │          │ SignalService │          │ OpService     │
└───────────────┘          └───────────────┘          └───────────────┘
        │                           │                           │
        │ 1. Load Resource          │                           │
        │ 2. Load Extension table   │                           │
        │ 3. Get Definition.code_ref│                           │
        │ 4. Factory.build(code_ref)│                           │
        ▼                           ▼                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        DB MODELS (Phase 1)                          │
│                     (libs/db/models/quant.py)                       │
├─────────────────────────────────────────────────────────────────────┤
│  PipelineDefinition.code_ref ─┐                                     │
│  StoreDefinition.code_ref ────┼─► "ExpressionPipeline"              │
│  AccessorDefinition.code_ref ─┘   "ParquetStore"                    │
│                                   "PITAccessor"                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FACTORIES (Phase 2)                          │
│                     (libs/data/registry.py)                         │
├─────────────────────────────────────────────────────────────────────┤
│  PIPELINE_FACTORY["ExpressionPipeline"] → ExpressionPipeline class  │
│  STORE_FACTORY["ParquetStore"] → ParquetStore class                 │
│  ACCESSOR_FACTORY["PITAccessor"] → PITAccessor class                │
│  OPS_REGISTRY["MEAN"] → mean_op function                            │
└─────────────────────────────────────────────────────────────────────┘
```

### Two-Table Pattern

Every quant resource uses a two-table pattern:
1. **Resource table**: Standard governance (RBAC, versioning, activity, hierarchy)
2. **Extension table**: Domain-specific data (code_ref, config, metrics)

```
┌─────────────────┐     ┌─────────────────────────┐
│    resources    │ 1─1 │  pipeline_definitions   │
├─────────────────┤     ├─────────────────────────┤
│ id (PK)         │◄────│ resource_id (PK, FK)    │
│ tenant_id       │     │ tenant_id               │
│ type            │     │ category                │
│ parent_id       │     │ code_ref                │ ← Links to Factory
│ name            │     │ interface_spec          │
│ metadata_json   │     │ guardrail_contracts     │
└─────────────────┘     └─────────────────────────┘
```

### Service Implementation Pattern

```python
# apps/api/services/dataset_service.py
from uuid import UUID
from libs.data.registry import PIPELINE_FACTORY, STORE_FACTORY, ACCESSOR_FACTORY
from libs.db.models.quant import (
    DatasetInstance, PipelineInstance, StoreInstance, AccessorInstance,
    PipelineDefinition, StoreDefinition, AccessorDefinition
)

class DatasetService:
    async def preview_dataset(
        self, session, actor, dataset_id: UUID, *, as_of_date=None
    ):
        """Execute a dataset and return data."""

        # 1. Load the DatasetInstance resource + extension
        instance = await session.get(DatasetInstance, dataset_id)

        # 2. Load component instances (composition pattern)
        store_inst = await session.get(StoreInstance, instance.store_instance_id)
        accessor_inst = await session.get(AccessorInstance, instance.accessor_instance_id)

        # 3. Load component definitions (to get code_ref)
        store_def = await session.get(StoreDefinition, store_inst.definition_resource_id)
        accessor_def = await session.get(AccessorDefinition, accessor_inst.definition_resource_id)

        # 4. Build execution objects from factories using code_ref
        store = STORE_FACTORY.build(
            store_def.code_ref,          # e.g., "ParquetStore"
            resource_id=str(store_inst.resource_id),
            config=store_inst.config_json or {},
            data_dir=self.data_dir,
        )
        accessor = ACCESSOR_FACTORY.build(
            accessor_def.code_ref,       # e.g., "PITAccessor"
            resource_id=str(accessor_inst.resource_id),
            config=accessor_inst.config_json or {},
            store=store,
        )

        # 5. Execute
        df = accessor.get(as_of_date=as_of_date)

        # 6. Emit activity
        envelope = ActivityEnvelope(...)
        await record_activity_with_outbox(session, envelope)

        return self._dataframe_to_response(df)
```

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
