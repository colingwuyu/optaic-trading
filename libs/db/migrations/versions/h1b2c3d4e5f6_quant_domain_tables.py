"""quant domain tables

Revision ID: h1b2c3d4e5f6
Revises: a1b2c3d4e5f6, g1a2b3c4d5e6
Create Date: 2026-01-01 00:00:00.000000

Adds extension tables for quant trading domain:
- Definition Resources: pipeline_definitions, store_definitions, accessor_definitions,
  op_definitions, op_macro_definitions, ml_module_definitions, portfolio_optimizer_definitions
- Instance Resources: pipeline_instances, store_instances, accessor_instances,
  dataset_instances, signal_specs, experiment_instances, model_instances,
  portfolio_optimizer_instances, backtest_instances
- Run Resources: backtest_runs, portfolio_optimization_runs, inference_runs, monitoring_runs
- Lineage: dataset_lineage
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = "h1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = ("a1b2c3d4e5f6", "g1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==========================================================================
    # DEFINITION RESOURCES
    # ==========================================================================

    # pipeline_definitions
    op.create_table(
        "pipeline_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("interface_spec", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(1024), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "compatibility_rules", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "guardrail_contracts", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("test_suite_ref", sa.String(1024), nullable=True),
        sa.Column(
            "evaluation_status", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_pipeline_defs_tenant_category",
        "pipeline_definitions",
        ["tenant_id", "category"],
    )

    # store_definitions
    op.create_table(
        "store_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("backend_type", sa.String(50), nullable=False),
        sa.Column("interface_spec", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(1024), nullable=True),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "guardrail_contracts", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_store_defs_tenant_backend",
        "store_definitions",
        ["tenant_id", "backend_type"],
    )

    # accessor_definitions
    op.create_table(
        "accessor_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("accessor_type", sa.String(50), nullable=False),
        sa.Column("interface_spec", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(1024), nullable=True),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "guardrail_contracts", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_accessor_defs_tenant_type",
        "accessor_definitions",
        ["tenant_id", "accessor_type"],
    )

    # op_definitions
    op.create_table(
        "op_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("signature", sa.String(512), nullable=False),
        sa.Column("interface_spec", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(1024), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_op_defs_tenant_category", "op_definitions", ["tenant_id", "category"]
    )

    # op_macro_definitions
    op.create_table(
        "op_macro_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("expression_text", sa.Text(), nullable=False),
        sa.Column("input_aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )

    # ml_module_definitions
    op.create_table(
        "ml_module_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("module_type", sa.String(50), nullable=False),
        sa.Column("interface_spec", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(1024), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "guardrail_contracts", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_ml_module_defs_tenant_type",
        "ml_module_definitions",
        ["tenant_id", "module_type"],
    )

    # portfolio_optimizer_definitions
    op.create_table(
        "portfolio_optimizer_definitions",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("algorithm_type", sa.String(50), nullable=False),
        sa.Column("interface_spec", sa.String(255), nullable=False),
        sa.Column("code_ref", sa.String(1024), nullable=True),
        sa.Column("input_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("parameters_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "guardrail_contracts", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_portfolio_opt_defs_tenant_algo",
        "portfolio_optimizer_definitions",
        ["tenant_id", "algorithm_type"],
    )

    # ==========================================================================
    # INSTANCE RESOURCES
    # ==========================================================================

    # pipeline_instances
    op.create_table(
        "pipeline_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("definition_resource_id", sa.Uuid(), nullable=False),
        sa.Column("definition_version_id", sa.Uuid(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("schedule_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["definition_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["definition_version_id"], ["resource_versions.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_pipeline_inst_tenant_def",
        "pipeline_instances",
        ["tenant_id", "definition_resource_id"],
    )

    # store_instances
    op.create_table(
        "store_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("definition_resource_id", sa.Uuid(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("physical_path", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["definition_resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        op.f("ix_store_instances_tenant_id"),
        "store_instances",
        ["tenant_id"],
        unique=False,
    )

    # accessor_instances
    op.create_table(
        "accessor_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("definition_resource_id", sa.Uuid(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["definition_resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        op.f("ix_accessor_instances_tenant_id"),
        "accessor_instances",
        ["tenant_id"],
        unique=False,
    )

    # dataset_instances
    op.create_table(
        "dataset_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_instance_id", sa.Uuid(), nullable=False),
        sa.Column("store_instance_id", sa.Uuid(), nullable=False),
        sa.Column("accessor_instance_id", sa.Uuid(), nullable=False),
        # External system registration (Instance = Registration Point)
        sa.Column("prefect_deployment_id", sa.String(255), nullable=True),
        sa.Column(
            "freshness_status", sa.String(32), nullable=False, server_default="unknown"
        ),
        sa.Column("last_data_date", sa.Date(), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["pipeline_instance_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["store_instance_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["accessor_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_dataset_inst_tenant_freshness",
        "dataset_instances",
        ["tenant_id", "freshness_status"],
    )

    # signal_specs
    op.create_table(
        "signal_specs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column(
            "allow_nan", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("neutral_value", sa.Float(), nullable=True),
        sa.Column("index_schema_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source_expression", sa.Text(), nullable=True),
        sa.Column(
            "input_dataset_ids",
            sa.JSON().with_variant(ARRAY(PG_UUID), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )

    # experiment_instances
    op.create_table(
        "experiment_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("expression_text", sa.Text(), nullable=False),
        sa.Column(
            "input_datasets_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "preview_config_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )

    # model_instances
    op.create_table(
        "model_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("definition_resource_id", sa.Uuid(), nullable=False),
        sa.Column("definition_version_id", sa.Uuid(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("artifact_path", sa.String(1024), nullable=True),
        # External system registration (Instance = Registration Point)
        sa.Column("mlflow_experiment_id", sa.String(255), nullable=True),
        sa.Column("mlflow_registered_model_name", sa.String(255), nullable=True),
        sa.Column("evidently_project_id", sa.String(255), nullable=True),
        sa.Column("training_dataset_id", sa.Uuid(), nullable=True),
        sa.Column("last_trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["definition_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["definition_version_id"], ["resource_versions.id"]),
        sa.ForeignKeyConstraint(["training_dataset_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_model_inst_tenant_def",
        "model_instances",
        ["tenant_id", "definition_resource_id"],
    )

    # portfolio_optimizer_instances
    op.create_table(
        "portfolio_optimizer_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("definition_resource_id", sa.Uuid(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("constraints_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "input_signal_ids",
            sa.JSON().with_variant(ARRAY(PG_UUID), "postgresql"),
            nullable=True,
        ),
        sa.Column("covariance_dataset_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["definition_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["covariance_dataset_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_portfolio_opt_inst_tenant_def",
        "portfolio_optimizer_instances",
        ["tenant_id", "definition_resource_id"],
    )
    op.create_index(
        op.f("ix_portfolio_optimizer_instances_tenant_id"),
        "portfolio_optimizer_instances",
        ["tenant_id"],
        unique=False,
    )

    # backtest_instances
    op.create_table(
        "backtest_instances",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assets_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("signals_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("date_range_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )

    # ==========================================================================
    # RUN RESOURCES
    # ==========================================================================

    # backtest_runs
    op.create_table(
        "backtest_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("backtest_instance_id", sa.Uuid(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("trades_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("equity_curve_ref", sa.String(1024), nullable=True),
        sa.Column("trades_ref", sa.String(1024), nullable=True),
        sa.Column("weights_history_ref", sa.String(1024), nullable=True),
        sa.Column(
            "input_versions_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["backtest_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_backtest_runs_tenant_instance",
        "backtest_runs",
        ["tenant_id", "backtest_instance_id"],
    )
    op.create_index(
        op.f("ix_backtest_runs_backtest_instance_id"),
        "backtest_runs",
        ["backtest_instance_id"],
        unique=False,
    )

    # portfolio_optimization_runs
    op.create_table(
        "portfolio_optimization_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("optimizer_instance_id", sa.Uuid(), nullable=False),
        sa.Column("weights_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "optimization_metrics_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "solver_status", sa.String(32), nullable=False, server_default="unknown"
        ),
        sa.Column("iterations", sa.Integer(), nullable=True),
        sa.Column(
            "constraints_satisfied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("active_constraints", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "input_versions_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["optimizer_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_portfolio_opt_runs_tenant_instance",
        "portfolio_optimization_runs",
        ["tenant_id", "optimizer_instance_id"],
    )
    op.create_index(
        op.f("ix_portfolio_optimization_runs_optimizer_instance_id"),
        "portfolio_optimization_runs",
        ["optimizer_instance_id"],
        unique=False,
    )

    # inference_runs
    op.create_table(
        "inference_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_instance_id", sa.Uuid(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("predictions_ref", sa.String(1024), nullable=True),
        sa.Column(
            "inference_params_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "input_versions_json", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["model_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_inference_runs_tenant_model",
        "inference_runs",
        ["tenant_id", "model_instance_id"],
    )
    op.create_index(
        op.f("ix_inference_runs_model_instance_id"),
        "inference_runs",
        ["model_instance_id"],
        unique=False,
    )

    # monitoring_runs
    op.create_table(
        "monitoring_runs",
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("parent_instance_id", sa.Uuid(), nullable=False),
        sa.Column("monitoring_type", sa.String(50), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("alerts_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("report_ref", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["parent_instance_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("resource_id"),
    )
    op.create_index(
        "ix_monitoring_runs_tenant_parent",
        "monitoring_runs",
        ["tenant_id", "parent_instance_id"],
    )
    op.create_index("ix_monitoring_runs_type", "monitoring_runs", ["monitoring_type"])
    op.create_index(
        op.f("ix_monitoring_runs_parent_instance_id"),
        "monitoring_runs",
        ["parent_instance_id"],
        unique=False,
    )

    # ==========================================================================
    # LINEAGE
    # ==========================================================================

    # dataset_lineage
    op.create_table(
        "dataset_lineage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("upstream_resource_id", sa.Uuid(), nullable=False),
        sa.Column("downstream_resource_id", sa.Uuid(), nullable=False),
        sa.Column("edge_kind", sa.String(50), nullable=False),
        sa.Column("upstream_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["upstream_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["downstream_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["upstream_version_id"], ["resource_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lineage_tenant_upstream",
        "dataset_lineage",
        ["tenant_id", "upstream_resource_id"],
    )
    op.create_index(
        "ix_lineage_tenant_downstream",
        "dataset_lineage",
        ["tenant_id", "downstream_resource_id"],
    )
    op.create_index(
        op.f("ix_dataset_lineage_tenant_id"),
        "dataset_lineage",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_lineage_upstream_resource_id"),
        "dataset_lineage",
        ["upstream_resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_lineage_downstream_resource_id"),
        "dataset_lineage",
        ["downstream_resource_id"],
        unique=False,
    )


def downgrade() -> None:
    # Lineage
    op.drop_index(
        op.f("ix_dataset_lineage_downstream_resource_id"), table_name="dataset_lineage"
    )
    op.drop_index(
        op.f("ix_dataset_lineage_upstream_resource_id"), table_name="dataset_lineage"
    )
    op.drop_index(op.f("ix_dataset_lineage_tenant_id"), table_name="dataset_lineage")
    op.drop_index("ix_lineage_tenant_downstream", table_name="dataset_lineage")
    op.drop_index("ix_lineage_tenant_upstream", table_name="dataset_lineage")
    op.drop_table("dataset_lineage")

    # Run Resources
    op.drop_index(
        op.f("ix_monitoring_runs_parent_instance_id"), table_name="monitoring_runs"
    )
    op.drop_index("ix_monitoring_runs_type", table_name="monitoring_runs")
    op.drop_index("ix_monitoring_runs_tenant_parent", table_name="monitoring_runs")
    op.drop_table("monitoring_runs")

    op.drop_index(
        op.f("ix_inference_runs_model_instance_id"), table_name="inference_runs"
    )
    op.drop_index("ix_inference_runs_tenant_model", table_name="inference_runs")
    op.drop_table("inference_runs")

    op.drop_index(
        op.f("ix_portfolio_optimization_runs_optimizer_instance_id"),
        table_name="portfolio_optimization_runs",
    )
    op.drop_index(
        "ix_portfolio_opt_runs_tenant_instance",
        table_name="portfolio_optimization_runs",
    )
    op.drop_table("portfolio_optimization_runs")

    op.drop_index(
        op.f("ix_backtest_runs_backtest_instance_id"), table_name="backtest_runs"
    )
    op.drop_index("ix_backtest_runs_tenant_instance", table_name="backtest_runs")
    op.drop_table("backtest_runs")

    # Instance Resources
    op.drop_table("backtest_instances")

    op.drop_index(
        op.f("ix_portfolio_optimizer_instances_tenant_id"),
        table_name="portfolio_optimizer_instances",
    )
    op.drop_index(
        "ix_portfolio_opt_inst_tenant_def", table_name="portfolio_optimizer_instances"
    )
    op.drop_table("portfolio_optimizer_instances")

    op.drop_index("ix_model_inst_tenant_def", table_name="model_instances")
    op.drop_table("model_instances")

    op.drop_table("experiment_instances")
    op.drop_table("signal_specs")

    op.drop_index("ix_dataset_inst_tenant_freshness", table_name="dataset_instances")
    op.drop_table("dataset_instances")

    op.drop_index(
        op.f("ix_accessor_instances_tenant_id"), table_name="accessor_instances"
    )
    op.drop_table("accessor_instances")

    op.drop_index(op.f("ix_store_instances_tenant_id"), table_name="store_instances")
    op.drop_table("store_instances")

    op.drop_index("ix_pipeline_inst_tenant_def", table_name="pipeline_instances")
    op.drop_table("pipeline_instances")

    # Definition Resources
    op.drop_index(
        "ix_portfolio_opt_defs_tenant_algo",
        table_name="portfolio_optimizer_definitions",
    )
    op.drop_table("portfolio_optimizer_definitions")

    op.drop_index("ix_ml_module_defs_tenant_type", table_name="ml_module_definitions")
    op.drop_table("ml_module_definitions")

    op.drop_table("op_macro_definitions")

    op.drop_index("ix_op_defs_tenant_category", table_name="op_definitions")
    op.drop_table("op_definitions")

    op.drop_index("ix_accessor_defs_tenant_type", table_name="accessor_definitions")
    op.drop_table("accessor_definitions")

    op.drop_index("ix_store_defs_tenant_backend", table_name="store_definitions")
    op.drop_table("store_definitions")

    op.drop_index("ix_pipeline_defs_tenant_category", table_name="pipeline_definitions")
    op.drop_table("pipeline_definitions")
