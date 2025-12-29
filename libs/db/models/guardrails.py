"""SQLAlchemy models for guardrails persistence."""

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def utcnow() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class ResourceContractBundle(Base):
    """Stores contract bundles associated with resources.

    Each resource can have one active bundle at a time.
    When a new bundle is upserted, the previous active bundle is deactivated.
    """

    __tablename__ = "resource_contract_bundles"

    bundle_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    resource_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    bundle_json: Mapped[str] = mapped_column(Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)

    __table_args__ = (
        Index("ix_resource_contract_bundles_resource_active", "resource_id", "is_active"),
    )


class ValidationReportRecord(Base):
    """Stores validation reports for audit and history.

    Reports are immutable once created - they represent a point-in-time validation result.
    """

    __tablename__ = "validation_reports"

    report_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ok: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    enforced_as: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    report_json: Mapped[str] = mapped_column(Text(), nullable=False)

    __table_args__ = (
        Index("ix_validation_reports_scope_target_created", "scope", "target_id", "created_at"),
    )
