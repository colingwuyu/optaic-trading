"""Add definition_uploads table for tracking uploaded plugins.

Revision ID: m6g7h8i9j0k1
Revises: l5f6g7h8i9j0
Create Date: 2026-01-05 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "m6g7h8i9j0k1"
down_revision: Union[str, None] = "l5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create definition_uploads table
    op.create_table(
        "definition_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        # Upload metadata
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("manifest_version", sa.String(50), nullable=False),
        sa.Column("upload_size_bytes", sa.BigInteger(), nullable=False),
        # Module information for plugin loading
        sa.Column("module_file", sa.String(255), nullable=False),
        sa.Column("class_name", sa.String(255), nullable=False),
        sa.Column("test_suite_file", sa.String(255), nullable=True),
        # Test execution status
        sa.Column(
            "evaluation_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        # Test results
        sa.Column("tests_total", sa.Integer(), nullable=True),
        sa.Column("tests_passed", sa.Integer(), nullable=True),
        sa.Column("tests_failed", sa.Integer(), nullable=True),
        sa.Column("test_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("test_output", sa.Text(), nullable=True),
        sa.Column("test_report_json", sa.JSON(), nullable=True),
        # Manifest content
        sa.Column("manifest_json", sa.JSON(), nullable=False, server_default="{}"),
        # Audit
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tests_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tests_completed_at", sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["principals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes
    op.create_index(
        "ix_definition_uploads_tenant_id",
        "definition_uploads",
        ["tenant_id"],
    )
    op.create_index(
        "ix_definition_uploads_resource_id",
        "definition_uploads",
        ["resource_id"],
        unique=True,
    )
    op.create_index(
        "ix_definition_uploads_uploaded_by",
        "definition_uploads",
        ["uploaded_by"],
    )
    op.create_index(
        "ix_definition_uploads_evaluation_status",
        "definition_uploads",
        ["evaluation_status"],
    )
    op.create_index(
        "ix_def_uploads_tenant_status",
        "definition_uploads",
        ["tenant_id", "evaluation_status"],
    )
    op.create_index(
        "ix_def_uploads_tenant_uploader",
        "definition_uploads",
        ["tenant_id", "uploaded_by"],
    )


def downgrade() -> None:
    op.drop_table("definition_uploads")
