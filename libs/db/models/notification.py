from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import JSONType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "principal_id",
            "activity_id",
            name="uq_notifications_tenant_principal_activity",
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    envelope: Mapped[dict] = mapped_column(JSONType)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    __table_args__ = (
        Index("ix_audit_log_tenant_processed", "tenant_id", "processed_at"),
    )


class NotificationPreference(Base):
    """Per-user notification preferences.

    Allows users to configure which activity types trigger notifications:
    - filter_mode: "all" (all activities), "mutations" (create/update/delete only),
                   or "custom" (user-defined patterns)
    - custom_actions: List of action patterns (e.g., ["resource.*", "chat.*"])
    - muted: If true, suppress all notifications
    """

    __tablename__ = "notification_preferences"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)

    # Filter mode: "all", "mutations", "custom"
    filter_mode: Mapped[str] = mapped_column(String(20), default="mutations")

    # Custom action patterns (JSON array), e.g., ["resource.*", "chat.*"]
    custom_actions: Mapped[list] = mapped_column(JSONType, default=list)

    # Mute all notifications
    muted: Mapped[bool] = mapped_column(Boolean, default=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "principal_id",
            name="uq_notification_prefs_tenant_principal",
        ),
        Index("ix_notification_prefs_tenant_principal", "tenant_id", "principal_id"),
    )
