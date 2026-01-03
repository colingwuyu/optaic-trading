"""Add orchestration and run tables.

Adds tables for execution orchestration:
- dataset_status: Execution metadata tracking for freshness
- pipeline_runs: Pipeline execution runs for dataset refresh
- experiment_runs: Expression evaluation runs (preview API)

Revision ID: i2c3d4e5f6g7
Revises: h1b2c3d4e5f6
Create Date: 2025-01-02 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "i2c3d4e5f6g7"
down_revision: str | None = "h1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create dataset_status table
    op.create_table(
        "dataset_status",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("last_pipeline_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pipeline_status", sa.String(32), nullable=True),
        sa.Column("last_data_date", sa.Date(), nullable=True),
        sa.Column("rows_processed", sa.BigInteger(), nullable=True),
        sa.Column("last_source_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_delay_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("dataset_id"),
    )
    op.create_index(
        "ix_dataset_status_tenant_status",
        "dataset_status",
        ["tenant_id", "last_pipeline_status"],
    )

    # Create pipeline_runs table
    op.create_table(
        "pipeline_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_instance_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False, server_default="overwrite"),
        sa.Column("orchestrator_kind", sa.String(32), nullable=True),
        sa.Column("orchestrator_run_id", sa.String(255), nullable=True),
        sa.Column("orchestrator_meta_json", sa.JSON(), nullable=True),
        sa.Column("rows_processed", sa.BigInteger(), nullable=True),
        sa.Column("start_data_date", sa.Date(), nullable=True),
        sa.Column("end_data_date", sa.Date(), nullable=True),
        sa.Column("extract_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("transform_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("load_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("input_versions_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["dataset_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_pipeline_runs_tenant_dataset",
        "pipeline_runs",
        ["tenant_id", "dataset_instance_id"],
    )
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])

    # Create experiment_runs table
    op.create_table(
        "experiment_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_instance_id", sa.Uuid(), nullable=False),
        sa.Column("expression_text", sa.Text(), nullable=False),
        sa.Column("input_versions_json", sa.JSON(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("orchestrator_kind", sa.String(32), nullable=True),
        sa.Column("orchestrator_run_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("result_columns", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("result_preview_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["experiment_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_experiment_runs_tenant_experiment",
        "experiment_runs",
        ["tenant_id", "experiment_instance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_runs_tenant_experiment", table_name="experiment_runs")
    op.drop_table("experiment_runs")

    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_tenant_dataset", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

    op.drop_index("ix_dataset_status_tenant_status", table_name="dataset_status")
    op.drop_table("dataset_status")
