from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import JSONType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromotionRequest(Base):
    __tablename__ = "promotion_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    pr_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"))
    moving_resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), index=True
    )
    from_scope_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )
    to_scope_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    placement_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    rbac_template_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    required_approvals: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_promotion_requests_tenant_to_scope", "tenant_id", "to_scope_id"),
        Index("ix_promotion_requests_tenant_status", "tenant_id", "status"),
        Index("ix_promotion_requests_tenant_moving", "tenant_id", "moving_resource_id"),
        UniqueConstraint("pr_resource_id", name="uq_promotion_requests_pr_resource_id"),
    )


class RbacTemplate(Base):
    __tablename__ = "rbac_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    policy: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_rbac_templates_tenant_name", "tenant_id", "name", unique=True),
    )
