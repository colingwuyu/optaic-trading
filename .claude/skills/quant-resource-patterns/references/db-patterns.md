# DB Model Patterns

## Standard Resource Model

```python
# libs/db/models/<domain>.py
from uuid import uuid4
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, Integer, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from libs.db.models.base import Base

class Signal(Base):
    __tablename__ = "signals"

    # Identity
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Domain columns
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_signals_tenant_created", "tenant_id", "created_at"),
    )
```

## Definition Resource Pattern

For plugin definitions that implement abstract interfaces:

```python
class PipelineDef(Base):
    __tablename__ = "pipeline_defs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Definition metadata
    kind: Mapped[str] = mapped_column(String(50), nullable=False)  # etl, expression, training
    interface_version: Mapped[str] = mapped_column(String(20), nullable=False)
    code_ref: Mapped[str] = mapped_column(String(255), nullable=True)  # artifact storage ref

    # Schema constraints
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=True)
    config_schema: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Evaluation state
    evaluation_status: Mapped[str] = mapped_column(String(20), default="pending")
```

## Instance Resource Pattern

For configured usages referencing definitions:

```python
class DatasetInstance(Base):
    __tablename__ = "dataset_instances"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # References to definitions (with versions)
    pipeline_def_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_defs.id"))
    pipeline_def_version: Mapped[str] = mapped_column(String(20))
    pipeline_config: Mapped[dict] = mapped_column(JSON)

    store_def_id: Mapped[UUID] = mapped_column(ForeignKey("store_defs.id"))
    store_config: Mapped[dict] = mapped_column(JSON)

    accessor_def_id: Mapped[UUID] = mapped_column(ForeignKey("accessor_defs.id"))
    accessor_config: Mapped[dict] = mapped_column(JSON)

    # Schedule
    schedule: Mapped[dict] = mapped_column(JSON, nullable=True)
    freshness_state: Mapped[str] = mapped_column(String(20), default="unknown")
```

## Common Patterns

### JSON Columns
```python
from libs.db.types import JSONType
config: Mapped[dict] = mapped_column(JSONType, nullable=True)
```

### UUID Arrays
```python
from libs.db.types import UUIDArrayType
upstream_ids: Mapped[list] = mapped_column(UUIDArrayType, nullable=True)
```

### Composite Indexes
```python
__table_args__ = (
    Index("ix_mymodel_tenant_type", "tenant_id", "resource_type"),
    UniqueConstraint("tenant_id", "name", name="uq_mymodel_tenant_name"),
)
```
