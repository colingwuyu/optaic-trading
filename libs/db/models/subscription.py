from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_subscriptions_tenant_principal_active",
            "tenant_id",
            "principal_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_subscriptions_tenant_resource_active",
            "tenant_id",
            "resource_id",
            "scope",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
