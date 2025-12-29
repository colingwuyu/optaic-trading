"""agent policies and cursors

Revision ID: f3c4d5e6f7a8
Revises: e2f4a6b8c9d0
Create Date: 2025-12-26 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "e2f4a6b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_policies",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_principal_id", sa.Uuid(), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_principal_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "agent_principal_id"),
    )
    op.create_index("ix_agent_policies_tenant", "agent_policies", ["tenant_id"], unique=False)

    op.create_table(
        "agent_cursors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_principal_id", sa.Uuid(), nullable=False),
        sa.Column("last_activity_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_principal_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "agent_principal_id"),
    )
    op.create_index("ix_agent_cursors_tenant", "agent_cursors", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_cursors_tenant", table_name="agent_cursors")
    op.drop_table("agent_cursors")
    op.drop_index("ix_agent_policies_tenant", table_name="agent_policies")
    op.drop_table("agent_policies")
