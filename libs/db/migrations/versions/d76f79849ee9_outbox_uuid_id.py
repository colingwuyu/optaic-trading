"""outbox uuid id

Revision ID: d76f79849ee9
Revises: bac5048f4565
Create Date: 2025-12-25 11:55:43.470841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d76f79849ee9"
down_revision: Union[str, Sequence[str], None] = "bac5048f4565"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    op.drop_table("outbox")
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if is_sqlite:
        op.create_index(
            "ix_outbox_publishable",
            "outbox",
            ["published_at", "created_at"],
            unique=False,
        )
    else:
        op.create_index(
            "ix_outbox_publishable",
            "outbox",
            [sa.literal_column("published_at NULLS FIRST"), "created_at"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    op.drop_index("ix_outbox_publishable", table_name="outbox")
    op.drop_table("outbox")
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if is_sqlite:
        op.create_index(
            "ix_outbox_publishable",
            "outbox",
            ["published_at", "created_at"],
            unique=False,
        )
    else:
        op.create_index(
            "ix_outbox_publishable",
            "outbox",
            [sa.literal_column("published_at NULLS FIRST"), "created_at"],
            unique=False,
        )
