"""merge requests and approvals

Revision ID: c7a1b2c3d4e5
Revises: f0c1e2d3a4b5
Create Date: 2025-12-26 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "f0c1e2d3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approver_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_id",
            "approver_id",
            name="uq_approvals_tenant_resource_approver",
        ),
    )
    op.create_index(
        op.f("ix_approvals_resource_id"), "approvals", ["resource_id"], unique=False
    )
    op.create_index(
        op.f("ix_approvals_tenant_id"), "approvals", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_approvals_tenant_resource",
        "approvals",
        ["tenant_id", "resource_id"],
        unique=False,
    )

    op.create_table(
        "merge_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("mr_resource_id", sa.Uuid(), nullable=False),
        sa.Column("target_resource_id", sa.Uuid(), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("target_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=4096), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"]),
        sa.ForeignKeyConstraint(["mr_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["target_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mr_resource_id", name="uq_merge_requests_mr_resource_id"),
    )
    op.create_index(
        op.f("ix_merge_requests_status"), "merge_requests", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_merge_requests_target_resource_id"),
        "merge_requests",
        ["target_resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merge_requests_tenant_id"),
        "merge_requests",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_merge_requests_tenant_target",
        "merge_requests",
        ["tenant_id", "target_resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_merge_requests_tenant_status",
        "merge_requests",
        ["tenant_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_merge_requests_tenant_status", table_name="merge_requests")
    op.drop_index("ix_merge_requests_tenant_target", table_name="merge_requests")
    op.drop_index(op.f("ix_merge_requests_tenant_id"), table_name="merge_requests")
    op.drop_index(
        op.f("ix_merge_requests_target_resource_id"), table_name="merge_requests"
    )
    op.drop_index(op.f("ix_merge_requests_status"), table_name="merge_requests")
    op.drop_table("merge_requests")

    op.drop_index("ix_approvals_tenant_resource", table_name="approvals")
    op.drop_index(op.f("ix_approvals_tenant_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_resource_id"), table_name="approvals")
    op.drop_table("approvals")
