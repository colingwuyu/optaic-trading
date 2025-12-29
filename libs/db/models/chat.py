from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import JSONType

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Channel(Base):
    __tablename__ = "channels"

    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel_kind: Mapped[str] = mapped_column(String(50))
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    sender_principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (
        Index("ix_messages_tenant_channel_created", "tenant_id", "channel_id", "created_at"),
    )

class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    bytes: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ReadReceipt(Base):
    __tablename__ = "read_receipts"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), primary_key=True)
    last_read_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
