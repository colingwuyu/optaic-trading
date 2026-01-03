from __future__ import annotations

from typing import Any, Mapping, Protocol
import asyncio
import os


class OrchestratorAdapter(Protocol):
    def submit_run(
        self,
        run_id: str,
        entrypoint: str,
        parameters: dict[str, Any],
        schedule: dict[str, Any] | None = None,
    ) -> str: ...

    def get_run_status(self, flow_run_id: str) -> str: ...


class RegistryAdapter(Protocol):
    def start_run(self, tags: dict[str, str] | None = None) -> str: ...

    def log_metrics(
        self, metrics: Mapping[str, float], *, step: int | None = None
    ) -> None: ...

    def log_artifacts(self, local_dir: str) -> None: ...

    def register_model(self, model_name: str, model_uri: str) -> str: ...


class PrefectOrchestrator:
    def __init__(self, api_url: str | None = None) -> None:
        self.api_url = api_url

    def submit_run(
        self,
        run_id: str,
        entrypoint: str,
        parameters: dict[str, Any],
        schedule: dict[str, Any] | None = None,
    ) -> str:
        if self.api_url:
            os.environ["PREFECT_API_URL"] = self.api_url
        from prefect.deployments import run_deployment

        _ = run_id
        _ = schedule
        state = run_deployment(entrypoint, parameters=parameters)
        flow_run_id = getattr(
            getattr(state, "state_details", None), "flow_run_id", None
        )
        if flow_run_id:
            return str(flow_run_id)
        return ""

    def get_run_status(self, flow_run_id: str) -> str:
        if self.api_url:
            os.environ["PREFECT_API_URL"] = self.api_url

        async def _read_state() -> str:
            from prefect.client import get_client

            async with get_client() as client:
                flow_run = await client.read_flow_run(flow_run_id)
                if not flow_run or not flow_run.state:
                    return "unknown"
                state_type = getattr(flow_run.state, "type", None)
                return str(state_type.value if state_type else flow_run.state)

        return _run_async(_read_state())


class MLflowRegistry:
    def __init__(self, tracking_uri: str | None = None) -> None:
        self.tracking_uri = tracking_uri
        self._run_id: str | None = None

    def start_run(self, tags: dict[str, str] | None = None) -> str:
        import mlflow

        if self.tracking_uri:
            mlflow.set_tracking_uri(self.tracking_uri)
        run = mlflow.start_run(tags=tags)
        self._run_id = run.info.run_id
        return self._run_id

    def log_metrics(
        self, metrics: Mapping[str, float], *, step: int | None = None
    ) -> None:
        import mlflow

        if self.tracking_uri:
            mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.log_metrics(dict(metrics), step=step, run_id=self._run_id)

    def log_artifacts(self, local_dir: str) -> None:
        import mlflow

        if self.tracking_uri:
            mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.log_artifacts(local_dir, run_id=self._run_id)

    def register_model(self, model_name: str, model_uri: str) -> str:
        import mlflow

        if self.tracking_uri:
            mlflow.set_tracking_uri(self.tracking_uri)
        result = mlflow.register_model(model_uri, model_name)
        return str(result.version)


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_running():
        raise RuntimeError(
            "Cannot run async Prefect client inside an active event loop."
        )
    return loop.run_until_complete(coro)
