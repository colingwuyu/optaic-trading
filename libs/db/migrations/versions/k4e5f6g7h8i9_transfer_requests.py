"""Add transfer_requests table.

Transfer requests implement a request/accept workflow:
1. Sender creates a TransferRequest
2. Recipient accepts or rejects
3. Upon acceptance, recipient chooses destination project
4. Resource is moved to recipient's project

Revision ID: k4e5f6g7h8i9
Revises: j3d4e5f6g7h8
Create Date: 2026-01-04 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "k4e5f6g7h8i9"
down_revision: str | None = "j3d4e5f6g7h8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transfer_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("destination_project_id", sa.Uuid(), nullable=True),
        sa.Column("message", sa.String(1024), nullable=True),
        sa.Column("response_message", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["destination_project_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transfer_requests_tenant_id",
        "transfer_requests",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_resource_id",
        "transfer_requests",
        ["resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_sender_id",
        "transfer_requests",
        ["sender_id"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_recipient_id",
        "transfer_requests",
        ["recipient_id"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_status",
        "transfer_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_tenant_status",
        "transfer_requests",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_tenant_recipient",
        "transfer_requests",
        ["tenant_id", "recipient_id"],
        unique=False,
    )
    op.create_index(
        "ix_transfer_requests_tenant_sender",
        "transfer_requests",
        ["tenant_id", "sender_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transfer_requests_tenant_sender", table_name="transfer_requests")
    op.drop_index(
        "ix_transfer_requests_tenant_recipient", table_name="transfer_requests"
    )
    op.drop_index("ix_transfer_requests_tenant_status", table_name="transfer_requests")
    op.drop_index("ix_transfer_requests_status", table_name="transfer_requests")
    op.drop_index("ix_transfer_requests_recipient_id", table_name="transfer_requests")
    op.drop_index("ix_transfer_requests_sender_id", table_name="transfer_requests")
    op.drop_index("ix_transfer_requests_resource_id", table_name="transfer_requests")
    op.drop_index("ix_transfer_requests_tenant_id", table_name="transfer_requests")
    op.drop_table("transfer_requests")
