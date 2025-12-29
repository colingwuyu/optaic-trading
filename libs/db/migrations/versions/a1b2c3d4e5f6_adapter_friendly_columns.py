"""Add adapter-friendly columns and system_engines table

Revision ID: a1b2c3d4e5f6
Revises: 7e8f9a0b1c2d
Create Date: 2025-12-28 19:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "7e8f9a0b1c2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- runs table: add adapter-friendly and status columns ---
    op.add_column(
        "runs",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
    )
    op.add_column(
        "runs",
        sa.Column(
            "status_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.add_column(
        "runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("requested_by_principal_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("orchestrator_kind", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("orchestrator_run_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("orchestrator_meta_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)

    # --- training_runs table: add adapter-friendly columns ---
    op.add_column(
        "training_runs",
        sa.Column("tracking_kind", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("tracking_run_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "training_runs",
        sa.Column("tracking_meta_json", sa.JSON(), nullable=True),
    )

    # --- model_versions table: add adapter-friendly columns ---
    op.add_column(
        "model_versions",
        sa.Column("registry_kind", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("registry_model_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("registry_model_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("registry_model_uri", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "model_versions",
        sa.Column("registry_meta_json", sa.JSON(), nullable=True),
    )

    # --- Create system_engines table ---
    op.create_table(
        "system_engines",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="disabled"),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("data_dir", sa.String(length=1024), nullable=True),
        sa.Column("db_uri", sa.String(length=1024), nullable=True),
        sa.Column("package_version", sa.String(length=64), nullable=True),
        sa.Column("last_migrated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_backup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health", sa.String(length=32), nullable=True),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("system_engines")

    # model_versions
    op.drop_column("model_versions", "registry_meta_json")
    op.drop_column("model_versions", "registry_model_uri")
    op.drop_column("model_versions", "registry_model_version")
    op.drop_column("model_versions", "registry_model_name")
    op.drop_column("model_versions", "registry_kind")

    # training_runs
    op.drop_column("training_runs", "tracking_meta_json")
    op.drop_column("training_runs", "tracking_run_id")
    op.drop_column("training_runs", "tracking_kind")

    # runs
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_column("runs", "orchestrator_meta_json")
    op.drop_column("runs", "orchestrator_run_id")
    op.drop_column("runs", "orchestrator_kind")
    op.drop_column("runs", "requested_by_principal_id")
    op.drop_column("runs", "error_summary")
    op.drop_column("runs", "finished_at")
    op.drop_column("runs", "started_at")
    op.drop_column("runs", "status_updated_at")
    op.drop_column("runs", "status")
