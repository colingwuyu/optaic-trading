import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import date
from uuid import uuid4
from libs.sdk_py import AsyncPlatformClient


@pytest.fixture
def mock_httpx_client():
    mock = AsyncMock()
    mock.request.return_value = MagicMock(
        status_code=200, json=lambda: {"id": "test-id"}
    )
    return mock


@pytest.fixture
def platform_client(mock_httpx_client):
    return AsyncPlatformClient(base_url="http://test.api", client=mock_httpx_client)


class TestDatasetsClient:
    @pytest.mark.asyncio
    async def test_create(self, platform_client, mock_httpx_client):
        name = "test-dataset"
        parent_id = uuid4()
        pipeline_inst_id = uuid4()
        store_inst_id = uuid4()
        accessor_inst_id = uuid4()

        await platform_client.datasets.create(
            name=name,
            parent_id=parent_id,
            pipeline_instance_id=pipeline_inst_id,
            store_instance_id=store_inst_id,
            accessor_instance_id=accessor_inst_id,
            freshness_status="fresh",
        )

        mock_httpx_client.request.assert_called_with(
            "POST",
            "/datasets",
            headers={},
            params=None,
            json={
                "name": name,
                "parent_id": str(parent_id),
                "pipeline_instance_id": str(pipeline_inst_id),
                "store_instance_id": str(store_inst_id),
                "accessor_instance_id": str(accessor_inst_id),
                "freshness_status": "fresh",
            },
        )

    @pytest.mark.asyncio
    async def test_preview_pit_date(self, platform_client, mock_httpx_client):
        dataset_id = uuid4()
        as_of_date = date(2025, 1, 1)

        await platform_client.datasets.preview(
            dataset_id=dataset_id, as_of_date=as_of_date, limit=50
        )

        # Check payload construction inside json arg of request call
        call_args = mock_httpx_client.request.call_args
        assert call_args[0][0] == "POST"
        assert f"/datasets/{dataset_id}/preview" in call_args[0][1]
        payload = call_args[1]["json"]
        assert payload["as_of_date"] == "2025-01-01"
        assert payload["limit"] == 50

    @pytest.mark.asyncio
    async def test_list_filters(self, platform_client, mock_httpx_client):
        parent_id = uuid4()
        await platform_client.datasets.list(
            parent_id=parent_id, freshness_status="stale", limit=10
        )

        call_args = mock_httpx_client.request.call_args
        assert call_args[0][0] == "GET"
        params = call_args[1]["params"]
        assert params["parent_id"] == str(parent_id)
        assert params["freshness_status"] == "stale"
        assert params["limit"] == 10


class TestSignalsClient:
    @pytest.mark.asyncio
    async def test_register(self, platform_client, mock_httpx_client):
        ds_id = uuid4()
        await platform_client.signals.register(
            dataset_id=ds_id, name="AlphaSignal", min_value=-5.0
        )

        mock_httpx_client.request.assert_called_with(
            "POST",
            "/signals",
            headers={},
            params=None,
            json={
                "dataset_id": str(ds_id),
                "name": "AlphaSignal",
                "min_value": -5.0,
                "max_value": 1.0,
                "allow_nan": False,
                "neutral_value": 0.0,
            },
        )

    @pytest.mark.asyncio
    async def test_validate_and_promote(self, platform_client, mock_httpx_client):
        sig_id = uuid4()

        await platform_client.signals.validate(sig_id)
        mock_httpx_client.request.assert_called_with(
            "POST", f"/signals/{sig_id}/validate", headers={}, params=None, json=None
        )

        await platform_client.signals.promote(sig_id)
        mock_httpx_client.request.assert_called_with(
            "POST", f"/signals/{sig_id}/promote", headers={}, params=None, json=None
        )


class TestOpsClient:
    @pytest.mark.asyncio
    async def test_evaluate(self, platform_client, mock_httpx_client):
        expr = "MEAN($close, 10)"
        ctx = {"close": uuid4()}
        start = date(2024, 1, 1)

        await platform_client.ops.evaluate(
            expression=expr, context=ctx, start_date=start
        )

        call_args = mock_httpx_client.request.call_args
        assert call_args[0][0] == "POST"
        assert "/ops/evaluate" in call_args[0][1]
        payload = call_args[1]["json"]
        assert payload["expression"] == expr
        assert payload["context"]["close"] == str(ctx["close"])
        assert payload["start_date"] == "2024-01-01"


class TestPipelinesClient:
    @pytest.mark.asyncio
    async def test_submit_definition(self, platform_client, mock_httpx_client):
        parent_id = uuid4()
        contracts = [{"kind": "signal.bounds", "spec": {"min": -1}}]

        await platform_client.pipelines.submit_definition(
            name="TestPipe",
            code_ref="MyRef",
            parent_id=parent_id,
            category="gen",
            guardrail_contracts=contracts,
        )

        call_args = mock_httpx_client.request.call_args
        payload = call_args[1]["json"]
        assert payload["name"] == "TestPipe"
        assert payload["guardrail_contracts"] == contracts
        assert payload["category"] == "gen"

    @pytest.mark.asyncio
    async def test_create_instance_full_config(
        self, platform_client, mock_httpx_client
    ):
        def_id = uuid4()
        parent_id = uuid4()
        schedule = {"cron": "* * * * *"}

        await platform_client.pipelines.create_instance(
            name="Inst1", definition_id=def_id, parent_id=parent_id, schedule=schedule
        )

        call_args = mock_httpx_client.request.call_args
        payload = call_args[1]["json"]
        assert payload["schedule"] == schedule
        assert payload["config"] == {}  # Default empty dict


class TestExperimentsClient:
    @pytest.mark.asyncio
    async def test_create_and_run(self, platform_client, mock_httpx_client):
        parent_id = uuid4()
        input_ds = {"v1": uuid4()}

        # Test Create
        await platform_client.experiments.create(
            name="Exp1",
            expression="AVG($v1)",
            parent_id=parent_id,
            input_datasets=input_ds,
        )

        call_args_create = mock_httpx_client.request.call_args_list[
            -1
        ]  # Most recent call if sequential, but here separate
        payload_create = call_args_create[1]["json"]
        assert payload_create["input_datasets"]["v1"] == str(input_ds["v1"])

        # Test Run
        exp_id = uuid4()
        await platform_client.experiments.run(exp_id, limit=500)

        call_args_run = mock_httpx_client.request.call_args
        assert f"/experiments/{exp_id}/run" in call_args_run[0][1]
        assert call_args_run[1]["json"]["limit"] == 500

    @pytest.mark.asyncio
    async def test_update_validation(self, platform_client):
        # Already covered in test_sdk.py but good to double check via logic
        with pytest.raises(ValueError):
            await platform_client.experiments.update(uuid4())

    @pytest.mark.asyncio
    async def test_save_as_macro(self, platform_client, mock_httpx_client):
        exp_id = uuid4()
        await platform_client.experiments.save_as_macro(exp_id, macro_name="MyMacro")

        call_args = mock_httpx_client.request.call_args
        assert f"/experiments/{exp_id}/save-as-macro" in call_args[0][1]
        assert call_args[1]["params"]["macro_name"] == "MyMacro"
