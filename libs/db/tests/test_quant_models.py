"""
Unit tests for quant domain models.

Tests all 21 quant domain models using SQLite (embedded Windows deployment mode):
- Definition Resources (7): PipelineDef, StoreDef, AccessorDef, OpDef, OpMacroDef, MLModuleDef, PortfolioOptimizerDef
- Instance Resources (9): PipelineInstance, StoreInstance, AccessorInstance, DatasetInstance, SignalSpec, ExperimentInstance, ModelInstance, PortfolioOptimizerInstance, BacktestInstance
- Run Resources (4): BacktestRun, PortfolioOptimizationRun, InferenceRun, MonitoringRun
- Lineage (1): DatasetLineage
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def utcnow() -> str:
    """Return current UTC time as ISO format string.

    Uses ISO format to avoid Python 3.12+ deprecation warning about
    the default sqlite3 datetime adapter.
    """
    return datetime.now(timezone.utc).isoformat()


def str_uuid() -> str:
    """Generate a string UUID for SQLite compatibility."""
    return str(uuid.uuid4())


async def create_resource(
    db_session: AsyncSession,
    tenant_id: str,
    principal_id: str,
    resource_type: str,
    name: str,
    resource_id: str | None = None,
) -> str:
    """Helper to create a resource with all required fields."""
    res_id = resource_id or str_uuid()
    await db_session.execute(
        text("""
            INSERT INTO resources (id, tenant_id, owner_principal_id, type, name, status, metadata, created_at, updated_at)
            VALUES (:id, :tenant_id, :owner_principal_id, :type, :name, :status, :metadata, :created_at, :updated_at)
        """),
        {
            "id": res_id,
            "tenant_id": tenant_id,
            "owner_principal_id": principal_id,
            "type": resource_type,
            "name": name,
            "status": "active",
            "metadata": "{}",
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    return res_id


# =============================================================================
# DEFINITION RESOURCE TESTS
# =============================================================================


class TestPipelineDefinition:
    """Tests for PipelineDefinition model."""

    @pytest.mark.asyncio
    async def test_create_pipeline_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating a PipelineDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO pipeline_definitions (
                    resource_id, tenant_id, category, interface_spec, code_ref,
                    input_schema, output_schema, parameters_schema,
                    compatibility_rules, guardrail_contracts, evaluation_status, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :category, :interface_spec, :code_ref,
                    :input_schema, :output_schema, :parameters_schema,
                    :compatibility_rules, :guardrail_contracts, :evaluation_status, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "category": "etl",
                "interface_spec": "optaic.interfaces.BasePipeline",
                "code_ref": "s3://pipelines/etl_v1.py",
                "input_schema": '{"type": "object"}',
                "output_schema": '{"type": "dataframe"}',
                "parameters_schema": '{"refresh_mode": "incremental"}',
                "compatibility_rules": '{"upstream_types": ["DatasetInstance"]}',
                "guardrail_contracts": '[{"kind": "pit.policy"}]',
                "evaluation_status": "approved",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)

    @pytest.mark.asyncio
    async def test_read_pipeline_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test reading a PipelineDefinition record."""
        # Insert first
        await db_session.execute(
            text("""
                INSERT INTO pipeline_definitions (
                    resource_id, tenant_id, category, interface_spec,
                    input_schema, output_schema, parameters_schema,
                    compatibility_rules, guardrail_contracts, evaluation_status, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :category, :interface_spec,
                    :input_schema, :output_schema, :parameters_schema,
                    :compatibility_rules, :guardrail_contracts, :evaluation_status, :created_at
                )
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "category": "expression",
                "interface_spec": "optaic.interfaces.ExpressionPipeline",
                "input_schema": '{"type": "object"}',
                "output_schema": '{"type": "dataframe"}',
                "parameters_schema": "{}",
                "compatibility_rules": "{}",
                "guardrail_contracts": "[]",
                "evaluation_status": "pending",
                "created_at": utcnow(),
            },
        )
        await db_session.flush()

        # Read back
        result = await db_session.execute(
            text(
                "SELECT category, interface_spec FROM pipeline_definitions WHERE resource_id = :id"
            ),
            {"id": str(test_resource)},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "expression"
        assert row[1] == "optaic.interfaces.ExpressionPipeline"


class TestStoreDefinition:
    """Tests for StoreDefinition model."""

    @pytest.mark.asyncio
    async def test_create_store_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating a StoreDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO store_definitions (
                    resource_id, tenant_id, backend_type, interface_spec,
                    code_ref, parameters_schema, guardrail_contracts, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :backend_type, :interface_spec,
                    :code_ref, :parameters_schema, :guardrail_contracts, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "backend_type": "parquet",
                "interface_spec": "optaic.interfaces.BaseStore",
                "code_ref": "s3://stores/parquet_store.py",
                "parameters_schema": '{"compression": "snappy"}',
                "guardrail_contracts": "[]",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestAccessorDefinition:
    """Tests for AccessorDefinition model."""

    @pytest.mark.asyncio
    async def test_create_accessor_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating an AccessorDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO accessor_definitions (
                    resource_id, tenant_id, accessor_type, interface_spec,
                    code_ref, parameters_schema, guardrail_contracts, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :accessor_type, :interface_spec,
                    :code_ref, :parameters_schema, :guardrail_contracts, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "accessor_type": "pit",
                "interface_spec": "optaic.interfaces.PITAccessor",
                "code_ref": "s3://accessors/pit_accessor.py",
                "parameters_schema": "{}",
                "guardrail_contracts": '[{"kind": "pit.knowledge_date_required"}]',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestOpDefinition:
    """Tests for OpDefinition model."""

    @pytest.mark.asyncio
    async def test_create_op_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating an OpDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO op_definitions (
                    resource_id, tenant_id, category, signature, interface_spec,
                    input_schema, output_schema, parameters_schema, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :category, :signature, :interface_spec,
                    :input_schema, :output_schema, :parameters_schema, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "category": "time_series",
                "signature": "MEAN(series, window)",
                "interface_spec": "optaic.ops.TimeSeriesOp",
                "input_schema": '{"series": "pd.Series", "window": "int"}',
                "output_schema": '{"type": "pd.Series"}',
                "parameters_schema": "{}",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestOpMacroDefinition:
    """Tests for OpMacroDefinition model."""

    @pytest.mark.asyncio
    async def test_create_op_macro_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating an OpMacroDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO op_macro_definitions (
                    resource_id, tenant_id, expression_text, input_aliases,
                    parameters_schema, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :expression_text, :input_aliases,
                    :parameters_schema, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "expression_text": "MEAN(CLOSE, 20) / MEAN(CLOSE, 50) - 1",
                "input_aliases": '["CLOSE"]',
                "parameters_schema": "{}",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestMLModuleDefinition:
    """Tests for MLModuleDefinition model."""

    @pytest.mark.asyncio
    async def test_create_ml_module_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating an MLModuleDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO ml_module_definitions (
                    resource_id, tenant_id, module_type, interface_spec,
                    code_ref, input_schema, output_schema, parameters_schema,
                    guardrail_contracts, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :module_type, :interface_spec,
                    :code_ref, :input_schema, :output_schema, :parameters_schema,
                    :guardrail_contracts, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "module_type": "xgboost_regressor",
                "interface_spec": "optaic.ml.BaseMLModule",
                "code_ref": "s3://ml/xgboost_module.py",
                "input_schema": '{"features": "pd.DataFrame"}',
                "output_schema": '{"predictions": "pd.Series"}',
                "parameters_schema": '{"n_estimators": 100}',
                "guardrail_contracts": "[]",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestPortfolioOptimizerDefinition:
    """Tests for PortfolioOptimizerDefinition model."""

    @pytest.mark.asyncio
    async def test_create_portfolio_optimizer_definition(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating a PortfolioOptimizerDefinition record."""
        result = await db_session.execute(
            text("""
                INSERT INTO portfolio_optimizer_definitions (
                    resource_id, tenant_id, algorithm_type, interface_spec,
                    code_ref, input_schema, output_schema, parameters_schema,
                    guardrail_contracts, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :algorithm_type, :interface_spec,
                    :code_ref, :input_schema, :output_schema, :parameters_schema,
                    :guardrail_contracts, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "algorithm_type": "mvo",
                "interface_spec": "optaic.portfolio.BaseOptimizer",
                "code_ref": "s3://optimizers/mvo.py",
                "input_schema": '{"signals": "pd.DataFrame", "covariance": "pd.DataFrame"}',
                "output_schema": '{"weights": "pd.Series"}',
                "parameters_schema": '{"risk_aversion": 1.0}',
                "guardrail_contracts": '[{"kind": "portfolio.constraints"}]',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


# =============================================================================
# INSTANCE RESOURCE TESTS
# =============================================================================


class TestPipelineInstance:
    """Tests for PipelineInstance model."""

    @pytest.mark.asyncio
    async def test_create_pipeline_instance(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a PipelineInstance record."""
        # Create a definition resource first
        def_resource_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "PipelineDefinition",
            "Test Pipeline Def",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO pipeline_instances (
                    resource_id, tenant_id, definition_resource_id,
                    config_json, schedule_json, status, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :definition_resource_id,
                    :config_json, :schedule_json, :status, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "definition_resource_id": def_resource_id,
                "config_json": '{"source": "bloomberg"}',
                "schedule_json": '{"cron": "0 18 * * 1-5"}',
                "status": "active",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestStoreInstance:
    """Tests for StoreInstance model."""

    @pytest.mark.asyncio
    async def test_create_store_instance(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a StoreInstance record."""
        def_resource_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "StoreDefinition",
            "Test Store Def",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO store_instances (
                    resource_id, tenant_id, definition_resource_id,
                    config_json, physical_path, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :definition_resource_id,
                    :config_json, :physical_path, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "definition_resource_id": def_resource_id,
                "config_json": '{"compression": "snappy"}',
                "physical_path": "s3://data/stores/spx_ohlcv/",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestAccessorInstance:
    """Tests for AccessorInstance model."""

    @pytest.mark.asyncio
    async def test_create_accessor_instance(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating an AccessorInstance record."""
        def_resource_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "AccessorDefinition",
            "Test Accessor Def",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO accessor_instances (
                    resource_id, tenant_id, definition_resource_id, config_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :definition_resource_id, :config_json, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "definition_resource_id": def_resource_id,
                "config_json": '{"date_column": "trade_date"}',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestDatasetInstance:
    """Tests for DatasetInstance model."""

    @pytest.mark.asyncio
    async def test_create_dataset_instance(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a DatasetInstance record with component references."""
        # Create component resources
        pipeline_inst_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "PipelineInstance",
            "Test PipelineInstance",
        )
        store_inst_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "StoreInstance",
            "Test StoreInstance",
        )
        accessor_inst_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "AccessorInstance",
            "Test AccessorInstance",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO dataset_instances (
                    resource_id, tenant_id, pipeline_instance_id, store_instance_id,
                    accessor_instance_id, freshness_status, last_data_date, row_count, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :pipeline_instance_id, :store_instance_id,
                    :accessor_instance_id, :freshness_status, :last_data_date, :row_count, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "pipeline_instance_id": pipeline_inst_id,
                "store_instance_id": store_inst_id,
                "accessor_instance_id": accessor_inst_id,
                "freshness_status": "fresh",
                "last_data_date": date(2024, 12, 31).isoformat(),
                "row_count": 50000,
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestSignalSpec:
    """Tests for SignalSpec model."""

    @pytest.mark.asyncio
    async def test_create_signal_spec(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating a SignalSpec record with bounds and schema."""
        result = await db_session.execute(
            text("""
                INSERT INTO signal_specs (
                    resource_id, tenant_id, min_value, max_value, allow_nan,
                    neutral_value, index_schema_json, source_expression, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :min_value, :max_value, :allow_nan,
                    :neutral_value, :index_schema_json, :source_expression, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "min_value": -1.0,
                "max_value": 1.0,
                "allow_nan": 0,  # SQLite uses 0/1 for boolean
                "neutral_value": 0.0,
                "index_schema_json": '{"columns": ["date", "entity"]}',
                "source_expression": "MEAN(CLOSE, 20) / MEAN(CLOSE, 50) - 1",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)

    @pytest.mark.asyncio
    async def test_signal_spec_bounds_validation(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test that signal spec can store proper bounds."""
        await db_session.execute(
            text("""
                INSERT INTO signal_specs (
                    resource_id, tenant_id, min_value, max_value, allow_nan, index_schema_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :min_value, :max_value, :allow_nan, :index_schema_json, :created_at
                )
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "min_value": -1.0,
                "max_value": 1.0,
                "allow_nan": 0,
                "index_schema_json": '{"columns": ["date", "entity"]}',
                "created_at": utcnow(),
            },
        )
        await db_session.flush()

        result = await db_session.execute(
            text(
                "SELECT min_value, max_value, allow_nan FROM signal_specs WHERE resource_id = :id"
            ),
            {"id": str(test_resource)},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == -1.0
        assert row[1] == 1.0
        assert row[2] == 0  # SQLite stores boolean as 0/1


class TestExperimentInstance:
    """Tests for ExperimentInstance model."""

    @pytest.mark.asyncio
    async def test_create_experiment_instance(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating an ExperimentInstance record."""
        result = await db_session.execute(
            text("""
                INSERT INTO experiment_instances (
                    resource_id, tenant_id, expression_text, input_datasets_json,
                    preview_config_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :expression_text, :input_datasets_json,
                    :preview_config_json, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "expression_text": "DELTA(CLOSE, 5) / CLOSE",
                "input_datasets_json": '{"CLOSE": "uuid-of-close-dataset"}',
                "preview_config_json": '{"start_date": "2024-01-01", "end_date": "2024-12-31"}',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestModelInstance:
    """Tests for ModelInstance model."""

    @pytest.mark.asyncio
    async def test_create_model_instance(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a ModelInstance record."""
        def_resource_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "MLModuleDefinition",
            "XGBoost Def",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO model_instances (
                    resource_id, tenant_id, definition_resource_id,
                    config_json, artifact_path, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :definition_resource_id,
                    :config_json, :artifact_path, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "definition_resource_id": def_resource_id,
                "config_json": '{"n_estimators": 100, "max_depth": 6}',
                "artifact_path": "s3://models/xgb_v1/",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestPortfolioOptimizerInstance:
    """Tests for PortfolioOptimizerInstance model."""

    @pytest.mark.asyncio
    async def test_create_portfolio_optimizer_instance(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a PortfolioOptimizerInstance record."""
        def_resource_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "PortfolioOptimizerDefinition",
            "MVO Def",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO portfolio_optimizer_instances (
                    resource_id, tenant_id, definition_resource_id,
                    config_json, constraints_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :definition_resource_id,
                    :config_json, :constraints_json, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "definition_resource_id": def_resource_id,
                "config_json": '{"risk_aversion": 1.5}',
                "constraints_json": '{"max_weight": 0.1, "min_weight": 0.0, "max_leverage": 1.0}',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestBacktestInstance:
    """Tests for BacktestInstance model."""

    @pytest.mark.asyncio
    async def test_create_backtest_instance(
        self, db_session: AsyncSession, test_tenant, test_resource
    ):
        """Test creating a BacktestInstance record."""
        result = await db_session.execute(
            text("""
                INSERT INTO backtest_instances (
                    resource_id, tenant_id, assets_json, signals_json,
                    date_range_json, config_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :assets_json, :signals_json,
                    :date_range_json, :config_json, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "assets_json": '{"universe": "SPX_500", "assets": ["AAPL", "MSFT", "GOOGL"]}',
                "signals_json": '{"momentum": "uuid-of-momentum-signal"}',
                "date_range_json": '{"start": "2020-01-01", "end": "2024-01-01"}',
                "config_json": '{"transaction_cost_bps": 10, "rebalance_freq": "monthly"}',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


# =============================================================================
# RUN RESOURCE TESTS
# =============================================================================


class TestBacktestRun:
    """Tests for BacktestRun model."""

    @pytest.mark.asyncio
    async def test_create_backtest_run(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a BacktestRun record with metrics."""
        bt_instance_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "BacktestInstance",
            "Test Backtest",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO backtest_runs (
                    resource_id, tenant_id, backtest_instance_id,
                    metrics_json, trades_json, equity_curve_ref, input_versions_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :backtest_instance_id,
                    :metrics_json, :trades_json, :equity_curve_ref, :input_versions_json, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "backtest_instance_id": bt_instance_id,
                "metrics_json": '{"sharpe_ratio": 1.45, "max_drawdown": -0.12, "total_return": 0.23}',
                "trades_json": "[]",
                "equity_curve_ref": "s3://runs/bt123/equity_curve.parquet",
                "input_versions_json": '{"momentum_signal": "v5"}',
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestPortfolioOptimizationRun:
    """Tests for PortfolioOptimizationRun model."""

    @pytest.mark.asyncio
    async def test_create_portfolio_optimization_run(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a PortfolioOptimizationRun record."""
        opt_instance_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "PortfolioOptimizerInstance",
            "Test Optimizer",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO portfolio_optimization_runs (
                    resource_id, tenant_id, optimizer_instance_id,
                    weights_json, optimization_metrics_json, solver_status,
                    iterations, constraints_satisfied, active_constraints, input_versions_json, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :optimizer_instance_id,
                    :weights_json, :optimization_metrics_json, :solver_status,
                    :iterations, :constraints_satisfied, :active_constraints, :input_versions_json, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "optimizer_instance_id": opt_instance_id,
                "weights_json": '{"AAPL": 0.15, "MSFT": 0.12, "GOOGL": 0.10}',
                "optimization_metrics_json": '{"expected_return": 0.12, "expected_volatility": 0.18}',
                "solver_status": "optimal",
                "iterations": 15,
                "constraints_satisfied": 1,  # SQLite uses 0/1 for boolean
                "active_constraints": '["max_weight"]',
                "input_versions_json": "{}",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestInferenceRun:
    """Tests for InferenceRun model."""

    @pytest.mark.asyncio
    async def test_create_inference_run(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating an InferenceRun record."""
        model_instance_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "ModelInstance",
            "Test Model",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO inference_runs (
                    resource_id, tenant_id, model_instance_id,
                    metrics_json, predictions_ref, inference_params_json,
                    input_versions_json, model_version, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :model_instance_id,
                    :metrics_json, :predictions_ref, :inference_params_json,
                    :input_versions_json, :model_version, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "model_instance_id": model_instance_id,
                "metrics_json": '{"inference_time_ms": 150, "num_predictions": 500}',
                "predictions_ref": "s3://runs/inf123/predictions.parquet",
                "inference_params_json": '{"batch_size": 64}',
                "input_versions_json": '{"features": "v3"}',
                "model_version": "v2.1.0",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


class TestMonitoringRun:
    """Tests for MonitoringRun model."""

    @pytest.mark.asyncio
    async def test_create_monitoring_run(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a MonitoringRun record."""
        parent_instance_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "ModelInstance",
            "Monitored Model",
        )

        result = await db_session.execute(
            text("""
                INSERT INTO monitoring_runs (
                    resource_id, tenant_id, parent_instance_id,
                    monitoring_type, metrics_json, alerts_json, report_ref, created_at
                )
                VALUES (
                    :resource_id, :tenant_id, :parent_instance_id,
                    :monitoring_type, :metrics_json, :alerts_json, :report_ref, :created_at
                )
                RETURNING resource_id
            """),
            {
                "resource_id": str(test_resource),
                "tenant_id": str(test_tenant),
                "parent_instance_id": parent_instance_id,
                "monitoring_type": "model_drift",
                "metrics_json": '{"overall_drift_score": 0.12, "features_with_drift": ["volatility_20d"]}',
                "alerts_json": '[{"type": "drift_warning", "feature": "volatility_20d", "severity": "warning"}]',
                "report_ref": "s3://runs/mon123/report.html",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == str(test_resource)


# =============================================================================
# LINEAGE TESTS
# =============================================================================


class TestDatasetLineage:
    """Tests for DatasetLineage model."""

    @pytest.mark.asyncio
    async def test_create_dataset_lineage(
        self, db_session: AsyncSession, test_tenant, test_principal, test_resource
    ):
        """Test creating a DatasetLineage record."""
        # Create upstream and downstream resources
        upstream_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "DatasetInstance",
            "Upstream Dataset",
        )
        downstream_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "DatasetInstance",
            "Downstream Signal",
        )

        lineage_id = str_uuid()
        result = await db_session.execute(
            text("""
                INSERT INTO dataset_lineage (
                    id, tenant_id, upstream_resource_id, downstream_resource_id,
                    edge_kind, created_at
                )
                VALUES (
                    :id, :tenant_id, :upstream_resource_id, :downstream_resource_id,
                    :edge_kind, :created_at
                )
                RETURNING id
            """),
            {
                "id": lineage_id,
                "tenant_id": str(test_tenant),
                "upstream_resource_id": upstream_id,
                "downstream_resource_id": downstream_id,
                "edge_kind": "input",
                "created_at": utcnow(),
            },
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == lineage_id

    @pytest.mark.asyncio
    async def test_query_lineage_graph(
        self, db_session: AsyncSession, test_tenant, test_principal
    ):
        """Test querying lineage to find upstream dependencies."""
        # Create a chain: dataset1 -> signal -> backtest
        dataset_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "DatasetInstance",
            "OHLCV Dataset",
        )
        signal_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "SignalSpec",
            "Momentum Signal",
        )
        backtest_id = await create_resource(
            db_session,
            str(test_tenant),
            str(test_principal),
            "BacktestInstance",
            "Strategy Backtest",
        )

        # Create lineage edges
        for upstream, downstream, edge_kind in [
            (dataset_id, signal_id, "input"),
            (signal_id, backtest_id, "signal"),
        ]:
            await db_session.execute(
                text("""
                    INSERT INTO dataset_lineage (id, tenant_id, upstream_resource_id, downstream_resource_id, edge_kind, created_at)
                    VALUES (:id, :tenant_id, :upstream, :downstream, :edge_kind, :created_at)
                """),
                {
                    "id": str_uuid(),
                    "tenant_id": str(test_tenant),
                    "upstream": upstream,
                    "downstream": downstream,
                    "edge_kind": edge_kind,
                    "created_at": utcnow(),
                },
            )
        await db_session.flush()

        # Query upstream dependencies of backtest
        result = await db_session.execute(
            text("""
                SELECT upstream_resource_id, edge_kind
                FROM dataset_lineage
                WHERE downstream_resource_id = :id
            """),
            {"id": backtest_id},
        )
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == signal_id
        assert rows[0][1] == "signal"

        # Query downstream dependents of dataset
        result = await db_session.execute(
            text("""
                SELECT downstream_resource_id, edge_kind
                FROM dataset_lineage
                WHERE upstream_resource_id = :id
            """),
            {"id": dataset_id},
        )
        rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == signal_id
        assert rows[0][1] == "input"


# =============================================================================
# TABLE EXISTENCE TESTS
# =============================================================================


class TestQuantTablesExist:
    """Tests that all quant domain tables exist in the database."""

    @pytest.mark.asyncio
    async def test_definition_tables_exist(self, db_session: AsyncSession):
        """Verify all Definition tables exist."""
        tables = [
            "pipeline_definitions",
            "store_definitions",
            "accessor_definitions",
            "op_definitions",
            "op_macro_definitions",
            "ml_module_definitions",
            "portfolio_optimizer_definitions",
        ]
        for table in tables:
            result = await db_session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            assert count is not None, f"Table {table} does not exist"

    @pytest.mark.asyncio
    async def test_instance_tables_exist(self, db_session: AsyncSession):
        """Verify all Instance tables exist."""
        tables = [
            "pipeline_instances",
            "store_instances",
            "accessor_instances",
            "dataset_instances",
            "signal_specs",
            "experiment_instances",
            "model_instances",
            "portfolio_optimizer_instances",
            "backtest_instances",
        ]
        for table in tables:
            result = await db_session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            assert count is not None, f"Table {table} does not exist"

    @pytest.mark.asyncio
    async def test_run_tables_exist(self, db_session: AsyncSession):
        """Verify all Run tables exist."""
        tables = [
            "backtest_runs",
            "portfolio_optimization_runs",
            "inference_runs",
            "monitoring_runs",
        ]
        for table in tables:
            result = await db_session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            assert count is not None, f"Table {table} does not exist"

    @pytest.mark.asyncio
    async def test_lineage_table_exists(self, db_session: AsyncSession):
        """Verify lineage table exists."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM dataset_lineage"))
        count = result.scalar()
        assert count is not None, "Table dataset_lineage does not exist"
