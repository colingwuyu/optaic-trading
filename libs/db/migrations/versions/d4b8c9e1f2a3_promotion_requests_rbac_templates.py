"""promotion requests and rbac templates

Revision ID: d4b8c9e1f2a3
Revises: c7a1b2c3d4e5
Create Date: 2025-12-26 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d4b8c9e1f2a3"
down_revision: Union[str, Sequence[str], None] = "c7a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("pr_resource_id", sa.Uuid(), nullable=False),
        sa.Column("moving_resource_id", sa.Uuid(), nullable=False),
        sa.Column("from_scope_id", sa.Uuid(), nullable=True),
        sa.Column("to_scope_id", sa.Uuid(), nullable=False),
        sa.Column(
            "placement_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("rbac_template_ref", sa.String(length=255), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"]),
        sa.ForeignKeyConstraint(["from_scope_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["moving_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["pr_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["to_scope_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pr_resource_id", name="uq_promotion_requests_pr_resource_id"
        ),
    )
    op.create_index(
        op.f("ix_promotion_requests_moving_resource_id"),
        "promotion_requests",
        ["moving_resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promotion_requests_status"),
        "promotion_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promotion_requests_tenant_id"),
        "promotion_requests",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promotion_requests_to_scope_id"),
        "promotion_requests",
        ["to_scope_id"],
        unique=False,
    )
    op.create_index(
        "ix_promotion_requests_tenant_to_scope",
        "promotion_requests",
        ["tenant_id", "to_scope_id"],
        unique=False,
    )
    op.create_index(
        "ix_promotion_requests_tenant_status",
        "promotion_requests",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_promotion_requests_tenant_moving",
        "promotion_requests",
        ["tenant_id", "moving_resource_id"],
        unique=False,
    )

    op.create_table(
        "rbac_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rbac_templates_tenant_id"),
        "rbac_templates",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_rbac_templates_tenant_name",
        "rbac_templates",
        ["tenant_id", "name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_rbac_templates_tenant_name", table_name="rbac_templates")
    op.drop_index(op.f("ix_rbac_templates_tenant_id"), table_name="rbac_templates")
    op.drop_table("rbac_templates")

    op.drop_index(
        "ix_promotion_requests_tenant_moving", table_name="promotion_requests"
    )
    op.drop_index(
        "ix_promotion_requests_tenant_status", table_name="promotion_requests"
    )
    op.drop_index(
        "ix_promotion_requests_tenant_to_scope", table_name="promotion_requests"
    )
    op.drop_index(
        op.f("ix_promotion_requests_to_scope_id"), table_name="promotion_requests"
    )
    op.drop_index(
        op.f("ix_promotion_requests_tenant_id"), table_name="promotion_requests"
    )
    op.drop_index(op.f("ix_promotion_requests_status"), table_name="promotion_requests")
    op.drop_index(
        op.f("ix_promotion_requests_moving_resource_id"),
        table_name="promotion_requests",
    )
    op.drop_table("promotion_requests")
