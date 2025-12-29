"""Add ML ops mapping fields

Revision ID: 7e8f9a0b1c2d
Revises: f3c4d5e6f7a8
Create Date: 2025-12-28 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7e8f9a0b1c2d"
down_revision: Union[str, Sequence[str], None] = "f3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("prefect_flow_run_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index("ix_runs_tenant_id", "runs", ["tenant_id"], unique=False)

    op.create_table(
        "training_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("mlflow_run_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index("ix_training_runs_tenant_id", "training_runs", ["tenant_id"], unique=False)

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("mlflow_registered_model", sa.String(length=255), nullable=True),
        sa.Column("mlflow_registered_model_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_versions_resource_id", "model_versions", ["resource_id"], unique=False)
    op.create_index("ix_model_versions_tenant_id", "model_versions", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_versions_tenant_id", table_name="model_versions")
    op.drop_index("ix_model_versions_resource_id", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_index("ix_training_runs_tenant_id", table_name="training_runs")
    op.drop_table("training_runs")
    op.drop_index("ix_runs_tenant_id", table_name="runs")
    op.drop_table("runs")
