"""subscriptions

Revision ID: e2f4a6b8c9d0
Revises: d4b8c9e1f2a3
Create Date: 2025-12-26 14:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f4a6b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4b8c9e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subscriptions_principal_id"), "subscriptions", ["principal_id"], unique=False)
    op.create_index(op.f("ix_subscriptions_resource_id"), "subscriptions", ["resource_id"], unique=False)
    op.create_index(op.f("ix_subscriptions_tenant_id"), "subscriptions", ["tenant_id"], unique=False)
    op.create_index(
        "ix_subscriptions_tenant_principal_active",
        "subscriptions",
        ["tenant_id", "principal_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_subscriptions_tenant_resource_active",
        "subscriptions",
        ["tenant_id", "resource_id", "scope"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_tenant_resource_active", table_name="subscriptions")
    op.drop_index("ix_subscriptions_tenant_principal_active", table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_tenant_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_resource_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_principal_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
