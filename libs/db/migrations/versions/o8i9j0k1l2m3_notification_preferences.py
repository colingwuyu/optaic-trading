"""add notification preferences table

Revision ID: o8i9j0k1l2m3
Revises: n7h8i9j0k1l2
Create Date: 2026-01-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o8i9j0k1l2m3"
down_revision: Union[str, None] = "n7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create notification_preferences table."""
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "filter_mode", sa.String(20), nullable=False, server_default="mutations"
        ),
        sa.Column("custom_actions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"]),
        sa.PrimaryKeyConstraint("id"),
        # SQLite requires unique constraint in create_table, not separate call
        sa.UniqueConstraint(
            "tenant_id", "principal_id", name="uq_notification_prefs_tenant_principal"
        ),
    )

    # Create indexes
    op.create_index(
        "ix_notification_prefs_tenant_id",
        "notification_preferences",
        ["tenant_id"],
    )
    op.create_index(
        "ix_notification_prefs_principal_id",
        "notification_preferences",
        ["principal_id"],
    )
    op.create_index(
        "ix_notification_prefs_tenant_principal",
        "notification_preferences",
        ["tenant_id", "principal_id"],
    )


def downgrade() -> None:
    """Drop notification_preferences table."""
    # Drop indexes first (constraint drops with table in SQLite)
    op.drop_index("ix_notification_prefs_tenant_principal", "notification_preferences")
    op.drop_index("ix_notification_prefs_principal_id", "notification_preferences")
    op.drop_index("ix_notification_prefs_tenant_id", "notification_preferences")
    op.drop_table("notification_preferences")
