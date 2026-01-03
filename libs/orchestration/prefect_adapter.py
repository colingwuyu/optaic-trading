"""PrefectOrchestrator for Prefect server integration.

Provides integration with Prefect for:
- Production deployments
- Distributed execution
- Flow monitoring and alerting

Ported from: optaic-v0/dev_tools/src/orchestration/flows.py
Adapted to work with the OrchestratorAdapter interface.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from uuid import UUID

from .adapter import OrchestratorAdapter, RunStatus, SubmitResult
from .dag import DependencyGraph

logger = logging.getLogger(__name__)


class PrefectOrchestrator(OrchestratorAdapter):
    """Prefect server integration for production orchestration.

    Requires Prefect to be installed and configured:
        pip install prefect

    Uses Prefect's flow/task API to create and submit flows based on
    the dependency graph. Each node becomes a Prefect task with
    wait_for ordering based on edges.

    Example:
        orchestrator = PrefectOrchestrator(api_url="http://localhost:4200/api")

        result = await orchestrator.submit_run(
            run_id=run.id,
            flow_definition=graph.to_dict(),
            config={"mode": "incremental"},
            tags={"tenant_id": str(tenant_id)},
        )

        # Prefect handles execution, we just poll for status
        status = await orchestrator.get_status(result.orchestrator_run_id)
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        work_pool: str = "default",
    ) -> None:
        """Initialize PrefectOrchestrator.

        Args:
            api_url: Prefect server API URL (defaults to PREFECT_API_URL env var)
            work_pool: Prefect work pool name for execution
        """
        self._api_url = api_url or os.getenv(
            "PREFECT_API_URL", "http://localhost:4200/api"
        )
        self._work_pool = work_pool

    @property
    def kind(self) -> str:
        return "prefect"

    async def submit_run(
        self,
        run_id: UUID,
        flow_definition: dict[str, Any],
        config: dict[str, Any],
        tags: dict[str, str],
    ) -> SubmitResult:
        """Submit a run to Prefect server.

        Creates a Prefect flow from the dependency graph and submits it
        for execution via the Prefect API.
        """
        try:
            from prefect import flow as prefect_flow
            from prefect import task as prefect_task
            from prefect.client import get_client
        except ImportError:
            raise ImportError("Prefect is required: pip install prefect")

        # Reconstruct graph from flow definition
        graph = DependencyGraph.from_dict(flow_definition)

        # Create the Prefect flow function
        @prefect_task(log_prints=True, persist_result=False)
        def run_node_task(node_id: str, mode: str) -> dict[str, Any]:
            """Execute a single node (runs in Prefect worker).

            Import inside task to avoid pickle issues (same pattern as optaic-v0).
            """
            from libs.data.registry import PIPELINE_FACTORY

            node = graph.nodes.get(node_id)
            if not node or not node.data.code_ref:
                return {"status": "skipped", "reason": "no code_ref"}

            try:
                pipeline = PIPELINE_FACTORY.build(
                    node.data.code_ref,
                    config={**node.data.config, **config},
                )
                result = pipeline.run(mode=mode)
                return {
                    "status": "success",
                    "rows_processed": getattr(result, "row_count", None),
                }
            except Exception as e:
                logger.exception(f"Node {node_id} failed: {e}")
                raise

        @prefect_flow(name=f"optaic-run-{run_id}")
        async def orchestration_flow(mode: str = "overwrite"):
            """Main orchestration flow."""
            # Get execution order
            batches = graph.get_execution_order()
            all_results = {}

            for batch in batches:
                # Submit batch tasks with wait_for ordering
                # Build task futures in order
                batch_futures = {}
                for node_id in batch:
                    # Get upstream node futures for wait_for
                    upstream = graph.get_upstream(UUID(node_id))
                    wait_for_futures = [
                        all_results.get(str(u.data.resource_id))
                        for u in upstream
                        if str(u.data.resource_id) in all_results
                    ]
                    # Filter None values
                    wait_for_futures = [f for f in wait_for_futures if f is not None]

                    # Submit task
                    if wait_for_futures:
                        future = run_node_task.submit(
                            node_id=node_id,
                            mode=mode,
                            wait_for=wait_for_futures,
                        )
                    else:
                        future = run_node_task.submit(
                            node_id=node_id,
                            mode=mode,
                        )
                    batch_futures[node_id] = future

                # Wait for all batch tasks
                for node_id, future in batch_futures.items():
                    try:
                        await future.result()  # Wait for completion
                        all_results[node_id] = future
                    except Exception as e:
                        logger.error(f"Node {node_id} failed: {e}")
                        raise

            return all_results

        # Submit the flow to Prefect
        async with get_client():
            # Run the flow (non-blocking deployment would require more setup)
            flow_run_state = await orchestration_flow(
                mode=config.get("mode", "overwrite"),
                return_state=True,
            )

            # Get the flow run ID from state
            flow_run_id = str(flow_run_state.state_details.flow_run_id)

            return SubmitResult(
                orchestrator_run_id=flow_run_id,
                orchestrator_kind="prefect",
                orchestrator_meta={
                    "nodes": len(graph.nodes),
                    "api_url": self._api_url,
                },
            )

    async def get_status(self, orchestrator_run_id: str) -> RunStatus:
        """Get current status from Prefect server."""
        try:
            from prefect.client import get_client
        except ImportError:
            return RunStatus(status="unknown", error_message="Prefect not installed")

        try:
            async with get_client() as client:
                flow_run = await client.read_flow_run(UUID(orchestrator_run_id))

                return RunStatus(
                    status=self._map_prefect_state(flow_run.state_name),
                    error_message=flow_run.state.message if flow_run.state else None,
                    started_at=flow_run.start_time,
                    finished_at=flow_run.end_time,
                )
        except Exception as e:
            logger.error(f"Failed to get status for {orchestrator_run_id}: {e}")
            return RunStatus(status="unknown", error_message=str(e))

    async def cancel_run(self, orchestrator_run_id: str) -> bool:
        """Cancel a running flow in Prefect."""
        try:
            from prefect.client import get_client
        except ImportError:
            return False

        try:
            async with get_client() as client:
                await client.set_flow_run_state(
                    flow_run_id=UUID(orchestrator_run_id),
                    state={"type": "CANCELLED"},
                )
                return True
        except Exception as e:
            logger.error(f"Failed to cancel {orchestrator_run_id}: {e}")
            return False

    async def get_logs(self, orchestrator_run_id: str) -> str:
        """Get logs from Prefect server."""
        try:
            from prefect.client import get_client
        except ImportError:
            return "Prefect not installed"

        try:
            async with get_client() as client:
                # Get flow run logs
                logs = await client.read_logs(flow_run_id=UUID(orchestrator_run_id))
                return "\n".join([log.message for log in logs])
        except Exception as e:
            logger.error(f"Failed to get logs for {orchestrator_run_id}: {e}")
            return f"Error getting logs: {e}"

    def _map_prefect_state(self, state_name: Optional[str]) -> str:
        """Map Prefect state to our RunStatus status."""
        if not state_name:
            return "unknown"

        mapping = {
            "PENDING": "queued",
            "SCHEDULED": "queued",
            "RUNNING": "running",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "CANCELLED": "cancelled",
            "CANCELLING": "cancelled",
            "CRASHED": "failed",
        }
        return mapping.get(state_name.upper(), "unknown")
