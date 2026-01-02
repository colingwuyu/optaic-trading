"""Tests for SDK clients.

Tests for the quant domain SDK clients:
- OpsClient
- DatasetsClient
- SignalsClient
- PipelinesClient
- ExperimentsClient
"""

from __future__ import annotations

from uuid import uuid4

import pytest


class TestImports:
    """Test that all SDK modules can be imported."""

    def test_import_client(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        assert AsyncPlatformClient is not None

    def test_import_ops_client(self) -> None:
        from libs.sdk_py import OpsClient

        assert OpsClient is not None

    def test_import_datasets_client(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert DatasetsClient is not None

    def test_import_signals_client(self) -> None:
        from libs.sdk_py import SignalsClient

        assert SignalsClient is not None

    def test_import_pipelines_client(self) -> None:
        from libs.sdk_py import PipelinesClient

        assert PipelinesClient is not None

    def test_import_experiments_client(self) -> None:
        from libs.sdk_py import ExperimentsClient

        assert ExperimentsClient is not None


class TestClientInstantiation:
    """Test client instantiation and lazy loading."""

    def test_client_creation(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(
            base_url="http://localhost:8000",
            principal_id=str(uuid4()),
            tenant_id=str(uuid4()),
        )
        assert client is not None
        assert client._base_url == "http://localhost:8000"

    def test_ops_client_lazy_loading(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(base_url="http://localhost:8000")
        # Check that private attribute is None initially
        assert client._ops is None
        # Access the property to trigger lazy loading
        ops = client.ops
        assert ops is not None
        assert client._ops is ops

    def test_datasets_client_lazy_loading(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(base_url="http://localhost:8000")
        assert client._datasets is None
        datasets = client.datasets
        assert datasets is not None
        assert client._datasets is datasets

    def test_signals_client_lazy_loading(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(base_url="http://localhost:8000")
        assert client._signals is None
        signals = client.signals
        assert signals is not None
        assert client._signals is signals

    def test_pipelines_client_lazy_loading(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(base_url="http://localhost:8000")
        assert client._pipelines is None
        pipelines = client.pipelines
        assert pipelines is not None
        assert client._pipelines is pipelines

    def test_experiments_client_lazy_loading(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(base_url="http://localhost:8000")
        assert client._experiments is None
        experiments = client.experiments
        assert experiments is not None
        assert client._experiments is experiments


class TestOpsClientHelpers:
    """Test OpsClient helper functions and parameter handling."""

    def test_drop_none(self) -> None:
        from libs.sdk_py.ops import _drop_none

        result = _drop_none({"a": 1, "b": None, "c": "test"})
        assert result == {"a": 1, "c": "test"}

    def test_to_str_with_uuid(self) -> None:
        from libs.sdk_py.ops import _to_str

        uid = uuid4()
        assert _to_str(uid) == str(uid)

    def test_to_str_with_string(self) -> None:
        from libs.sdk_py.ops import _to_str

        assert _to_str("test") == "test"

    def test_to_str_with_none(self) -> None:
        from libs.sdk_py.ops import _to_str

        assert _to_str(None) is None


class TestDatasetsClientHelpers:
    """Test DatasetsClient helper functions."""

    def test_drop_none(self) -> None:
        from libs.sdk_py.datasets import _drop_none

        result = _drop_none({"parent_id": None, "status": "fresh", "limit": 50})
        assert result == {"status": "fresh", "limit": 50}


class TestSignalsClientHelpers:
    """Test SignalsClient helper functions."""

    def test_drop_none(self) -> None:
        from libs.sdk_py.signals import _drop_none

        result = _drop_none({"name": "test", "parent_id": None})
        assert result == {"name": "test"}


class TestPipelinesClientHelpers:
    """Test PipelinesClient helper functions."""

    def test_drop_none(self) -> None:
        from libs.sdk_py.pipelines import _drop_none

        result = _drop_none({"name": "test", "schedule": None, "config": {}})
        assert result == {"name": "test", "config": {}}


class TestExperimentsClientHelpers:
    """Test ExperimentsClient helper functions."""

    def test_drop_none(self) -> None:
        from libs.sdk_py.experiments import _drop_none

        result = _drop_none({"expression": "MEAN($x, 20)", "description": None})
        assert result == {"expression": "MEAN($x, 20)"}


class TestClientMethods:
    """Test client method signatures."""

    def test_ops_client_has_list_method(self) -> None:
        from libs.sdk_py import OpsClient

        assert hasattr(OpsClient, "list")
        assert callable(getattr(OpsClient, "list"))

    def test_ops_client_has_get_method(self) -> None:
        from libs.sdk_py import OpsClient

        assert hasattr(OpsClient, "get")
        assert callable(getattr(OpsClient, "get"))

    def test_ops_client_has_evaluate_method(self) -> None:
        from libs.sdk_py import OpsClient

        assert hasattr(OpsClient, "evaluate")
        assert callable(getattr(OpsClient, "evaluate"))

    def test_datasets_client_has_create_method(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert hasattr(DatasetsClient, "create")
        assert callable(getattr(DatasetsClient, "create"))

    def test_datasets_client_has_list_method(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert hasattr(DatasetsClient, "list")

    def test_datasets_client_has_get_method(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert hasattr(DatasetsClient, "get")

    def test_datasets_client_has_status_method(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert hasattr(DatasetsClient, "status")

    def test_datasets_client_has_preview_method(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert hasattr(DatasetsClient, "preview")

    def test_datasets_client_has_refresh_method(self) -> None:
        from libs.sdk_py import DatasetsClient

        assert hasattr(DatasetsClient, "refresh")

    def test_signals_client_has_register_method(self) -> None:
        from libs.sdk_py import SignalsClient

        assert hasattr(SignalsClient, "register")

    def test_signals_client_has_validate_method(self) -> None:
        from libs.sdk_py import SignalsClient

        assert hasattr(SignalsClient, "validate")

    def test_signals_client_has_promote_method(self) -> None:
        from libs.sdk_py import SignalsClient

        assert hasattr(SignalsClient, "promote")

    def test_pipelines_client_has_submit_definition_method(self) -> None:
        from libs.sdk_py import PipelinesClient

        assert hasattr(PipelinesClient, "submit_definition")

    def test_pipelines_client_has_deploy_definition_method(self) -> None:
        from libs.sdk_py import PipelinesClient

        assert hasattr(PipelinesClient, "deploy_definition")

    def test_pipelines_client_has_create_instance_method(self) -> None:
        from libs.sdk_py import PipelinesClient

        assert hasattr(PipelinesClient, "create_instance")

    def test_pipelines_client_has_run_method(self) -> None:
        from libs.sdk_py import PipelinesClient

        assert hasattr(PipelinesClient, "run")

    def test_experiments_client_has_create_method(self) -> None:
        from libs.sdk_py import ExperimentsClient

        assert hasattr(ExperimentsClient, "create")

    def test_experiments_client_has_run_method(self) -> None:
        from libs.sdk_py import ExperimentsClient

        assert hasattr(ExperimentsClient, "run")

    def test_experiments_client_has_update_method(self) -> None:
        from libs.sdk_py import ExperimentsClient

        assert hasattr(ExperimentsClient, "update")

    def test_experiments_client_has_save_as_macro_method(self) -> None:
        from libs.sdk_py import ExperimentsClient

        assert hasattr(ExperimentsClient, "save_as_macro")


class TestExperimentsUpdateValidation:
    """Test ExperimentsClient update validation."""

    @pytest.mark.asyncio
    async def test_update_requires_at_least_one_field(self) -> None:
        from libs.sdk_py import AsyncPlatformClient

        client = AsyncPlatformClient(base_url="http://localhost:8000")
        experiments = client.experiments

        with pytest.raises(ValueError, match="At least one field"):
            await experiments.update(uuid4())


class TestDateConversion:
    """Test date conversion in client methods."""

    def test_ops_evaluate_date_conversion(self) -> None:
        # The evaluate method should accept date objects and convert to ISO strings
        from libs.sdk_py.ops import OpsClient

        # Test that the method signature accepts date
        import inspect

        sig = inspect.signature(OpsClient.evaluate)
        params = sig.parameters

        assert "start_date" in params
        assert "end_date" in params

    def test_datasets_preview_date_conversion(self) -> None:
        from libs.sdk_py.datasets import DatasetsClient

        import inspect

        sig = inspect.signature(DatasetsClient.preview)
        params = sig.parameters

        assert "start_date" in params
        assert "end_date" in params
        assert "as_of_date" in params

    def test_experiments_run_date_conversion(self) -> None:
        from libs.sdk_py.experiments import ExperimentsClient

        import inspect

        sig = inspect.signature(ExperimentsClient.run)
        params = sig.parameters

        assert "start_date" in params
        assert "end_date" in params


class TestAllExports:
    """Test that __all__ exports are correct."""

    def test_all_exports(self) -> None:
        from libs.sdk_py import __all__

        expected = [
            "AsyncPlatformClient",
            "DatasetsClient",
            "ExperimentsClient",
            "OpsClient",
            "PipelinesClient",
            "SignalsClient",
        ]
        assert sorted(__all__) == sorted(expected)
