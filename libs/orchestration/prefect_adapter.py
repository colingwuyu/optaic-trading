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

from .adapter import DeploymentResult, OrchestratorAdapter, RunStatus, SubmitResult
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
            from prefect.client.orchestration import get_client
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
            from prefect.client.orchestration import get_client
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
            from prefect.client.orchestration import get_client
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
            from prefect.client.orchestration import get_client
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

    # =========================================================================
    # Deployment Management (Flow Execution Resources)
    # =========================================================================

    async def create_deployment(
        self,
        instance_id: UUID,
        flow_name: str,
        flow_template: str,
        parameters: dict[str, Any],
        schedule: Optional[dict[str, Any]] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> DeploymentResult:
        """Create a Prefect deployment for an Instance.

        Creates a static deployment that can be triggered to create flow runs.
        """
        try:
            from prefect import flow as prefect_flow
            from prefect.deployments import Deployment
        except ImportError:
            # Fall back to local deployment if Prefect not available
            logger.warning("Prefect not installed, creating local deployment")
            return DeploymentResult(
                deployment_id=f"local-{instance_id}",
                orchestrator_kind="local",
                deployment_meta={"flow_template": flow_template},
            )

        try:
            # Create a simple flow function for this deployment
            @prefect_flow(name=f"{flow_template}-{instance_id}")
            async def instance_flow(
                mode: str = "incremental",
                config: dict = None,
            ):
                """Flow for Instance execution.

                Note: Actual execution logic is implemented in the flow template.
                This is a placeholder flow that will be replaced with the real
                implementation based on flow_template.
                """
                config = config or {}
                logger.info(f"Executing {flow_template} for {instance_id}")
                return {"status": "completed", "mode": mode}

            # Build schedule if provided
            prefect_schedule = None
            if schedule:
                if schedule.get("cron"):
                    from prefect.schedules import CronSchedule

                    prefect_schedule = CronSchedule(cron=schedule["cron"])
                elif schedule.get("interval_seconds"):
                    from prefect.schedules import IntervalSchedule

                    prefect_schedule = IntervalSchedule(
                        interval=schedule["interval_seconds"]
                    )

            # Create deployment
            deployment = await Deployment.build_from_flow(
                flow=instance_flow,
                name=flow_name,
                work_pool_name=self._work_pool,
                parameters=parameters,
                schedule=prefect_schedule,
                tags=list((tags or {}).values()),
            )
            deployment_id = await deployment.apply()

            return DeploymentResult(
                deployment_id=str(deployment_id),
                orchestrator_kind="prefect",
                deployment_meta={
                    "flow_template": flow_template,
                    "work_pool": self._work_pool,
                    "has_schedule": schedule is not None,
                },
            )

        except Exception as e:
            logger.error(f"Failed to create deployment: {e}")
            # Fall back to local deployment
            return DeploymentResult(
                deployment_id=f"local-{instance_id}",
                orchestrator_kind="local",
                deployment_meta={"flow_template": flow_template, "error": str(e)},
            )

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a Prefect deployment."""
        if deployment_id.startswith("local-"):
            return True  # Local deployments don't need cleanup

        try:
            from prefect.client.orchestration import get_client
        except ImportError:
            return True

        try:
            async with get_client() as client:
                await client.delete_deployment(UUID(deployment_id))
                return True
        except Exception as e:
            logger.error(f"Failed to delete deployment {deployment_id}: {e}")
            return False

    async def trigger_deployment(
        self,
        deployment_id: str,
        run_id: UUID,
        parameters: Optional[dict[str, Any]] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> SubmitResult:
        """Trigger a run on an existing Prefect deployment."""
        if deployment_id.startswith("local-"):
            # Local deployment - use submit_run
            return await self.submit_run(
                run_id=run_id,
                flow_definition={"nodes": [], "edges": []},
                config=parameters or {},
                tags=tags or {},
            )

        try:
            from prefect.client.orchestration import get_client
        except ImportError:
            raise ImportError("Prefect is required for deployment triggers")

        try:
            async with get_client() as client:
                flow_run = await client.create_flow_run_from_deployment(
                    deployment_id=UUID(deployment_id),
                    parameters=parameters or {},
                    tags=list((tags or {}).values()),
                )

                return SubmitResult(
                    orchestrator_run_id=str(flow_run.id),
                    orchestrator_kind="prefect",
                    orchestrator_meta={
                        "deployment_id": deployment_id,
                        "run_id": str(run_id),
                    },
                )

        except Exception as e:
            logger.error(f"Failed to trigger deployment {deployment_id}: {e}")
            raise

    async def update_schedule(
        self,
        deployment_id: str,
        schedule: dict[str, Any],
    ) -> bool:
        """Update the schedule of a Prefect deployment.

        Args:
            deployment_id: Prefect deployment ID
            schedule: New schedule config (cron or interval_seconds)

        Returns:
            True if update succeeded
        """
        if deployment_id.startswith("local-"):
            logger.info("Local deployment schedule update (no-op)")
            return True

        try:
            from prefect.client.orchestration import get_client
        except ImportError:
            logger.warning("Prefect not installed, cannot update schedule")
            return False

        try:
            async with get_client() as client:
                # Parse schedule
                prefect_schedule = None
                if schedule:
                    if schedule.get("cron"):
                        from prefect.schedules import CronSchedule

                        prefect_schedule = CronSchedule(cron=schedule["cron"])
                    elif schedule.get("interval_seconds"):
                        from prefect.schedules import IntervalSchedule

                        prefect_schedule = IntervalSchedule(
                            interval=schedule["interval_seconds"]
                        )

                # Update deployment schedule
                await client.update_deployment(
                    deployment_id=UUID(deployment_id),
                    schedule=prefect_schedule,
                )
                logger.info(f"Updated schedule for deployment {deployment_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to update schedule for {deployment_id}: {e}")
            return False

    async def get_deployment(
        self,
        deployment_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get deployment details from Prefect.

        Args:
            deployment_id: Prefect deployment ID

        Returns:
            Deployment details dict or None if not found
        """
        if deployment_id.startswith("local-"):
            return {"id": deployment_id, "kind": "local"}

        try:
            from prefect.client.orchestration import get_client
        except ImportError:
            return None

        try:
            async with get_client() as client:
                deployment = await client.read_deployment(UUID(deployment_id))
                return {
                    "id": str(deployment.id),
                    "name": deployment.name,
                    "flow_name": deployment.flow_name,
                    "work_pool_name": deployment.work_pool_name,
                    "schedule": deployment.schedule.dict()
                    if deployment.schedule
                    else None,
                    "parameters": deployment.parameters,
                    "is_schedule_active": deployment.is_schedule_active,
                }
        except Exception as e:
            logger.error(f"Failed to get deployment {deployment_id}: {e}")
            return None

    async def get_task_runs(
        self,
        flow_run_id: str,
    ) -> list[dict[str, Any]]:
        """Get task runs for a flow run.

        Args:
            flow_run_id: Prefect flow run ID

        Returns:
            List of task run details
        """
        try:
            from prefect.client.orchestration import get_client
        except ImportError:
            return []

        try:
            async with get_client() as client:
                task_runs = await client.read_task_runs(
                    flow_run_filter={"id": {"any_": [UUID(flow_run_id)]}}
                )
                return [
                    {
                        "id": str(tr.id),
                        "name": tr.name,
                        "state": tr.state_name,
                        "started_at": tr.start_time,
                        "finished_at": tr.end_time,
                    }
                    for tr in task_runs
                ]
        except Exception as e:
            logger.error(f"Failed to get task runs for {flow_run_id}: {e}")
            return []
