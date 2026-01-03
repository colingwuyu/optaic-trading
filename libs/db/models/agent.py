from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import JSONType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentPolicy(Base):
    __tablename__ = "agent_policies"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    agent_principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("principals.id"), primary_key=True
    )
    policy: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_agent_policies_tenant", "tenant_id"),)


class AgentCursor(Base):
    __tablename__ = "agent_cursors"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    agent_principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("principals.id"), primary_key=True
    )
    last_activity_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (Index("ix_agent_cursors_tenant", "tenant_id"),)
