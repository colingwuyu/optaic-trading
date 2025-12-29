from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MergeRequest(Base):
    __tablename__ = "merge_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    mr_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    target_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    source_ref: Mapped[str] = mapped_column(String(255))
    target_ref: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    required_approvals: Mapped[int] = mapped_column(default=1)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("mr_resource_id", name="uq_merge_requests_mr_resource_id"),
        Index("ix_merge_requests_tenant_target", "tenant_id", "target_resource_id"),
        Index("ix_merge_requests_tenant_status", "tenant_id", "status"),
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    decision: Mapped[str] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_id",
            "approver_id",
            name="uq_approvals_tenant_resource_approver",
        ),
        Index("ix_approvals_tenant_resource", "tenant_id", "resource_id"),
    )
