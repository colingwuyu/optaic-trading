"""
SystemEngine model for ops observability of orchestration/tracking engines.

This is a small table for monitoring engine health and tracking upgrade state.
Business logic should depend on Adapter interfaces, not this table.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemEngine(Base):
    """
    Ops observability table for orchestration/tracking engines.

    This table tracks:
    - Engine mode (local/remote/disabled)
    - Connection info (base_url, db_uri)
    - Upgrade state (package_version, last_migrated_at, last_backup_at)
    - Health status for monitoring

    NOTE: Business logic should depend on Adapter interfaces, not this table.
    This is for ops visibility and safer upgrades only.
    """

    __tablename__ = "system_engines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g., "prefect", "mlflow"
    mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disabled"
    )  # local|remote|disabled
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    data_dir: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    db_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    package_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health: Mapped[str | None] = mapped_column(String(32), nullable=True)  # e.g., "healthy", "degraded"
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # freeform config
