"""Definition Upload tracking model.

Tracks uploaded Definition plugins (PipelineDef, OpDef, etc.) with:
- Original upload metadata (filename, size, manifest version)
- Module information (module_file, class_name for factory registration)
- Test execution results (status, counts, duration, output)
- Audit trail (who uploaded, when)

This table links to:
- Resource: The Definition resource created from the upload
- Principal: Who uploaded the definition

The module_file and class_name are critical for plugin_loader to:
1. Find the module in artifact storage
2. Register the class in FactoryRegistry
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base
from ..types import JSONType

if TYPE_CHECKING:
    from .identity import Principal, Tenant
    from .resource import Resource


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DefinitionUpload(Base):
    """Tracks uploaded Definition plugins.

    When a user uploads a ZIP containing a Definition plugin, this record
    stores the upload metadata and test results. The actual files are stored
    in the artifact folder referenced by Resource.artifact_ref.

    Workflow:
    1. User uploads ZIP → DefinitionUploadService processes it
    2. ZIP extracted to artifact folder (Resource.artifact_ref)
    3. Tests run if test_suite_file in manifest
    4. DefinitionUpload record created with results
    5. On startup, plugin_loader uses module_file to load plugin

    Status flow:
    - evaluation_status: pending → running → passed|failed|skipped
    - Resource.status: draft (if tests fail) | active (if tests pass/skipped)
    """

    __tablename__ = "definition_uploads"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), unique=True, index=True
    )

    # Upload metadata
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_version: Mapped[str] = mapped_column(String(50), nullable=False)
    upload_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Module information (critical for plugin loading)
    module_file: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # e.g., "pipeline.py"
    class_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # e.g., "CustomPipeline" (becomes code_ref)

    # Test suite reference (if provided in manifest)
    test_suite_file: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Test execution status
    evaluation_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending|running|passed|failed|skipped

    # Test results
    tests_total: Mapped[int | None] = mapped_column(nullable=True)
    tests_passed: Mapped[int | None] = mapped_column(nullable=True)
    tests_failed: Mapped[int | None] = mapped_column(nullable=True)
    test_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Test output (stdout/stderr, truncated if too long)
    test_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Detailed test report (JSON with per-test results)
    test_report_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    # Manifest content (stored for reference)
    manifest_json: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Audit
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    # When tests were last run (for re-run tracking)
    tests_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tests_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id])
    resource: Mapped["Resource"] = relationship("Resource", foreign_keys=[resource_id])
    uploader: Mapped["Principal"] = relationship(
        "Principal", foreign_keys=[uploaded_by]
    )

    __table_args__ = (
        Index("ix_def_uploads_tenant_status", "tenant_id", "evaluation_status"),
        Index("ix_def_uploads_tenant_uploader", "tenant_id", "uploaded_by"),
    )

    def __repr__(self) -> str:
        return f"<DefinitionUpload {self.original_filename} ({self.evaluation_status})>"
