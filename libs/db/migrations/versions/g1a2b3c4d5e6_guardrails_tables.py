"""guardrails tables

Revision ID: g1a2b3c4d5e6
Revises: 9a3c0b5dd2e5
Create Date: 2025-12-29 11:12:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "9a3c0b5dd2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create resource_contract_bundles table
    op.create_table(
        "resource_contract_bundles",
        sa.Column("bundle_id", sa.String(255), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("resource_version_id", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bundle_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.PrimaryKeyConstraint("bundle_id"),
    )
    op.create_index(
        "ix_resource_contract_bundles_resource_active",
        "resource_contract_bundles",
        ["resource_id", "is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resource_contract_bundles_resource_id"),
        "resource_contract_bundles",
        ["resource_id"],
        unique=False,
    )

    # Create validation_reports table
    op.create_table(
        "validation_reports",
        sa.Column("report_id", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("enforced_as", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index(
        op.f("ix_validation_reports_target_id"),
        "validation_reports",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        "ix_validation_reports_scope_target_created",
        "validation_reports",
        ["scope", "target_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_validation_reports_scope_target_created", table_name="validation_reports")
    op.drop_index(op.f("ix_validation_reports_target_id"), table_name="validation_reports")
    op.drop_table("validation_reports")

    op.drop_index("ix_resource_contract_bundles_resource_active", table_name="resource_contract_bundles")
    op.drop_index(op.f("ix_resource_contract_bundles_resource_id"), table_name="resource_contract_bundles")
    op.drop_table("resource_contract_bundles")
