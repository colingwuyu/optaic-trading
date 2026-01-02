from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import String, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from ..types import JSONType

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    resource_id: Mapped[UUID] = mapped_column(index=True)
    resource_type: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target_principal_id: Mapped[UUID | None] = mapped_column(ForeignKey("principals.id"), nullable=True)
    visibility: Mapped[str] = mapped_column(String(50), default="resource") # private|resource|scope|tenant|system
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    authz_decision: Mapped[str | None] = mapped_column(String(50), nullable=True) # allow|deny
    correlation_id: Mapped[UUID] = mapped_column(default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "correlation_id",
            "action",
            "resource_id",
            name="uq_activities_tenant_correlation_action_resource",
        ),
        Index("ix_activities_tenant_created_desc", "tenant_id", created_at.desc()),
        Index(
            "ix_activities_tenant_actor_created_desc",
            "tenant_id",
            "actor_principal_id",
            created_at.desc(),
        ),
        Index(
            "ix_activities_tenant_resource_created_desc",
            "tenant_id",
            "resource_id",
            created_at.desc(),
        ),
    )

class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    topic: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Index for processing unpublished items: query with WHERE published_at IS NULL ORDER BY created_at
        Index(
            "ix_outbox_publishable",
            "published_at",
            "created_at",
        ),
    )
