"""Transfer request model for governance workflows.

Transfer uses a request/accept workflow where:
1. Sender creates a TransferRequest
2. Recipient accepts or rejects
3. Upon acceptance, recipient chooses destination project
4. Resource is moved to recipient's project
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransferRequest(Base):
    """Transfer request for resource ownership change.

    Workflow:
    - Status 'pending': Awaiting recipient response
    - Status 'accepted': Recipient accepted, resource transferred
    - Status 'rejected': Recipient declined
    - Status 'cancelled': Sender cancelled
    - Status 'expired': Request timed out
    """

    __tablename__ = "transfer_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # The resource being transferred
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)

    # Sender (current owner requesting transfer)
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)

    # Recipient (proposed new owner)
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)

    # Destination project (set by recipient upon acceptance)
    destination_project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )

    # Optional message from sender
    message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Recipient's response message
    response_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Status: pending, accepted, rejected, cancelled, expired
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_transfer_requests_tenant_status", "tenant_id", "status"),
        Index("ix_transfer_requests_tenant_recipient", "tenant_id", "recipient_id"),
        Index("ix_transfer_requests_tenant_sender", "tenant_id", "sender_id"),
        # Only one pending transfer per resource
        UniqueConstraint(
            "resource_id",
            name="uq_transfer_requests_pending_resource",
            # Note: This constraint will be enforced at application level
            # for pending status only, as SQLite doesn't support partial indexes
        ),
    )
