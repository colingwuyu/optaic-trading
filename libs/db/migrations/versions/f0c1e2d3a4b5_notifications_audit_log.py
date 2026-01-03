"""notifications and audit log

Revision ID: f0c1e2d3a4b5
Revises: b977f47758b1
Create Date: 2025-12-26 09:12:42.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f0c1e2d3a4b5"
down_revision: Union[str, Sequence[str], None] = "b977f47758b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "principal_id",
            "activity_id",
            name="uq_notifications_tenant_principal_activity",
        ),
    )
    op.create_index(
        op.f("ix_notifications_activity_id"),
        "notifications",
        ["activity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_principal_id"),
        "notifications",
        ["principal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"], unique=False
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_activity_id"), "audit_log", ["activity_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_log_tenant_id"), "audit_log", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_log_processed_at"), "audit_log", ["processed_at"], unique=False
    )
    op.create_index(
        "ix_audit_log_tenant_processed",
        "audit_log",
        ["tenant_id", "processed_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_log_tenant_processed", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_processed_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_tenant_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_activity_id"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(op.f("ix_notifications_tenant_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_principal_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_activity_id"), table_name="notifications")
    op.drop_table("notifications")
