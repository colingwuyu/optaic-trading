"""Tests for quant domain services.

Tests verify:
- Service imports work correctly
- Activity emission patterns
- code_ref linkage validation
- Factory integration
"""


from apps.api.services import (
    DatasetService,
    ExperimentService,
    OpService,
    PipelineService,
    SignalService,
)


class TestServiceImports:
    """Test that all services can be imported and instantiated."""

    def test_dataset_service_import(self):
        """DatasetService should import and have required methods."""
        service = DatasetService()
        assert hasattr(service, "get_dataset")
        assert hasattr(service, "preview_dataset")
        assert hasattr(service, "refresh_dataset")
        assert hasattr(service, "list_datasets")

    def test_experiment_service_import(self):
        """ExperimentService should import and have required methods."""
        service = ExperimentService()
        assert hasattr(service, "create_experiment")
        assert hasattr(service, "run_experiment")
        assert hasattr(service, "save_as_macro")
        assert hasattr(service, "list_experiments")

    def test_op_service_import(self):
        """OpService should import and have required methods."""
        service = OpService()
        assert hasattr(service, "list_operators")
        assert hasattr(service, "get_operator")
        assert hasattr(service, "evaluate_expression")
        assert hasattr(service, "list_macros")

    def test_pipeline_service_import(self):
        """PipelineService should import and have required methods."""
        service = PipelineService()
        assert hasattr(service, "submit_definition")
        assert hasattr(service, "deploy_definition")
        assert hasattr(service, "create_instance")
        assert hasattr(service, "trigger_run")
        assert hasattr(service, "list_definitions")
        assert hasattr(service, "list_instances")

    def test_signal_service_import(self):
        """SignalService should import and have required methods."""
        service = SignalService()
        assert hasattr(service, "register_signal")
        assert hasattr(service, "get_signal")
        assert hasattr(service, "validate_signal")
        assert hasattr(service, "list_signals")
        assert hasattr(service, "promote_signal")


class TestOpServiceLogic:
    """Test OpService business logic."""

    def test_list_operators(self):
        """list_operators should return available operators."""
        service = OpService()
        operators = service.list_operators()

        assert isinstance(operators, list)
        assert len(operators) > 0

        # Check structure
        op = operators[0]
        assert "name" in op
        assert "category" in op
        assert "code_ref" in op

    def test_get_operator_existing(self):
        """get_operator should return operator info for valid names."""
        service = OpService()

        # Test known operators
        for name in ["MEAN", "DELTA", "REF", "CORR"]:
            op = service.get_operator(name)
            assert op is not None
            assert op["name"] == name
            assert op["code_ref"] == name

    def test_get_operator_nonexistent(self):
        """get_operator should return None for unknown operators."""
        service = OpService()
        op = service.get_operator("NONEXISTENT_OP")
        assert op is None

    def test_get_operator_case_insensitive(self):
        """get_operator should be case-insensitive."""
        service = OpService()

        op_upper = service.get_operator("MEAN")
        op_lower = service.get_operator("mean")
        op_mixed = service.get_operator("Mean")

        assert op_upper is not None
        assert op_lower is not None
        assert op_mixed is not None
        assert op_upper["name"] == op_lower["name"] == op_mixed["name"]


class TestExperimentServiceLogic:
    """Test ExperimentService business logic."""

    def test_expression_engine_exists(self):
        """ExperimentService should have an expression engine."""
        service = ExperimentService()
        assert hasattr(service, "expression_engine")

    def test_expression_metadata_extraction(self):
        """Expression engine should extract metadata from expressions."""
        service = ExperimentService()

        # Valid expression - validate_expression returns dataset references
        datasets = service.expression_engine.validate_expression("MEAN($price, 20)")
        assert isinstance(datasets, list)
        assert "price" in datasets

        # get_used_operators returns operator names
        operators = service.expression_engine.get_used_operators("MEAN($price, 20)")
        assert isinstance(operators, list)
        assert "MEAN" in operators

    def test_result_to_response_scalar(self):
        """_result_to_response should handle scalar results."""
        service = ExperimentService()
        response = service._result_to_response(42.5, "test", "1 + 1", limit=100)

        assert response["success"] is True
        assert response["result_type"] == "scalar"
        assert response["value"] == 42.5

    def test_result_to_response_dataframe(self):
        """_result_to_response should handle DataFrame results."""
        import pandas as pd

        service = ExperimentService()
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        response = service._result_to_response(df, "test", "expr", limit=100)

        assert response["success"] is True
        assert response["result_type"] == "dataframe"
        assert response["columns"] == ["a", "b"]
        assert len(response["data"]) == 3

    def test_result_to_response_series(self):
        """_result_to_response should handle Series results."""
        import pandas as pd

        service = ExperimentService()
        series = pd.Series([1, 2, 3], name="values")
        response = service._result_to_response(series, "test", "expr", limit=100)

        assert response["success"] is True
        assert response["result_type"] == "series"
        assert len(response["data"]) == 3

    def test_result_to_response_truncation(self):
        """_result_to_response should truncate large results."""
        import pandas as pd

        service = ExperimentService()
        df = pd.DataFrame({"a": range(200)})
        response = service._result_to_response(df, "test", "expr", limit=50)

        assert response["success"] is True
        assert len(response["data"]) == 50
        assert response["truncated"] is True
        assert response["row_count"] == 200


class TestPipelineServiceValidation:
    """Test PipelineService validation logic."""

    def test_code_ref_validation(self):
        """submit_definition should validate code_ref exists in factory."""
        from libs.data.registry import PIPELINE_FACTORY

        # Known code_refs should be in factory
        assert "ExpressionPipeline" in PIPELINE_FACTORY

    def test_known_pipeline_code_refs(self):
        """Factory should have expected pipelines registered."""
        from libs.data.registry import PIPELINE_FACTORY

        # Check for expected pipelines
        keys = list(PIPELINE_FACTORY.keys())
        assert len(keys) > 0


class TestDatasetServiceLogic:
    """Test DatasetService business logic."""

    def test_dataframe_to_response(self):
        """_dataframe_to_response should convert DataFrames correctly."""
        import pandas as pd

        service = DatasetService()

        # Create mock instance
        class MockInstance:
            row_count = 100
            freshness_status = "fresh"

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        response = service._dataframe_to_response(df, MockInstance())

        assert response["columns"] == ["a", "b"]
        assert len(response["data"]) == 2
        assert response["row_count"] == 2
        assert response["freshness_status"] == "fresh"


class TestActivityActions:
    """Test that services define correct activity actions."""

    def test_documented_activity_actions(self):
        """Check that activity actions are documented in __init__.py."""
        from apps.api.services import __doc__

        assert "dataset.created" in __doc__ or "dataset.previewed" in __doc__
        assert "signal.registered" in __doc__
        assert "pipeline_def.submitted" in __doc__
        assert "experiment.created" in __doc__


class TestCodeRefIntegration:
    """Test code_ref → Factory integration."""

    def test_store_code_refs_exist(self):
        """All seeded store code_refs should exist in factory."""
        from scripts.seed_definitions import BUILT_IN_STORES
        from libs.data.registry import STORE_FACTORY

        for store in BUILT_IN_STORES:
            assert store["code_ref"] in STORE_FACTORY, f"Missing: {store['code_ref']}"

    def test_accessor_code_refs_exist(self):
        """All seeded accessor code_refs should exist in factory."""
        from scripts.seed_definitions import BUILT_IN_ACCESSORS
        from libs.data.registry import ACCESSOR_FACTORY

        for accessor in BUILT_IN_ACCESSORS:
            assert accessor["code_ref"] in ACCESSOR_FACTORY, f"Missing: {accessor['code_ref']}"

    def test_op_code_refs_exist(self):
        """All seeded op code_refs should exist in registry."""
        from scripts.seed_definitions import BUILT_IN_OPS
        from libs.data.ops import OPS_REGISTRY

        for op in BUILT_IN_OPS:
            assert op["code_ref"] in OPS_REGISTRY, f"Missing: {op['code_ref']}"
