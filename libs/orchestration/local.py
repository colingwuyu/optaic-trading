"""LocalOrchestrator for in-process DAG execution.

Provides a simple, in-process execution engine for:
- Testing without external dependencies
- Embedded deployments
- Small-scale execution

Uses ThreadPoolExecutor for parallel node execution within
topologically sorted batches.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

from .adapter import OrchestratorAdapter, RunStatus, SubmitResult
from .dag import DependencyGraph

logger = logging.getLogger(__name__)


@dataclass
class LocalRunState:
    """Internal state for a local run."""

    run_id: UUID
    flow_definition: dict[str, Any]
    config: dict[str, Any]
    tags: dict[str, str]

    # Execution state
    status: str = "queued"  # queued, running, completed, failed, cancelled
    error_message: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)

    # Timing
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Node results
    node_results: dict[str, Any] = field(default_factory=dict)
    node_errors: dict[str, str] = field(default_factory=dict)

    # Logs
    logs: list[str] = field(default_factory=list)

    # Cancellation
    cancelled: bool = False


class LocalOrchestrator(OrchestratorAdapter):
    """In-process DAG executor using ThreadPoolExecutor.

    Suitable for:
    - Testing without Prefect
    - Embedded/single-machine deployments
    - Development environments

    Executes nodes in topological order, with parallel execution
    within each batch (nodes with no dependencies on each other).

    Example:
        orchestrator = LocalOrchestrator(max_workers=4)

        result = await orchestrator.submit_run(
            run_id=run.id,
            flow_definition=graph.to_dict(),
            config={"mode": "incremental"},
            tags={"tenant_id": str(tenant_id)},
        )

        # Poll for completion
        while True:
            status = await orchestrator.get_status(result.orchestrator_run_id)
            if status.status in ("completed", "failed"):
                break
            await asyncio.sleep(1)
    """

    def __init__(
        self,
        max_workers: int = 4,
        node_executor: Optional[Callable] = None,
    ) -> None:
        """Initialize LocalOrchestrator.

        Args:
            max_workers: Maximum parallel threads for node execution
            node_executor: Optional custom node executor function.
                Signature: async def execute_node(node_id, node_type, code_ref, config) -> dict
                If not provided, uses default executor that imports from libs.data.registry
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._runs: dict[str, LocalRunState] = {}
        self._node_executor = node_executor or self._default_node_executor

    @property
    def kind(self) -> str:
        return "local"

    async def submit_run(
        self,
        run_id: UUID,
        flow_definition: dict[str, Any],
        config: dict[str, Any],
        tags: dict[str, str],
    ) -> SubmitResult:
        """Submit a run for local execution.

        Creates a local run state and schedules async execution.
        """
        local_run_id = str(uuid4())

        state = LocalRunState(
            run_id=run_id,
            flow_definition=flow_definition,
            config=config,
            tags=tags,
        )
        self._runs[local_run_id] = state

        # Schedule execution (non-blocking)
        asyncio.create_task(self._execute_run(local_run_id))

        node_count = len(flow_definition.get("nodes", []))
        return SubmitResult(
            orchestrator_run_id=local_run_id,
            orchestrator_kind="local",
            orchestrator_meta={"nodes": node_count},
        )

    async def get_status(self, orchestrator_run_id: str) -> RunStatus:
        """Get current status of a local run."""
        state = self._runs.get(orchestrator_run_id)
        if not state:
            return RunStatus(status="unknown", error_message="Run not found")

        return RunStatus(
            status=state.status,
            error_message=state.error_message,
            metrics=state.metrics,
            started_at=state.started_at,
            finished_at=state.finished_at,
        )

    async def cancel_run(self, orchestrator_run_id: str) -> bool:
        """Cancel a running execution."""
        state = self._runs.get(orchestrator_run_id)
        if not state:
            return False

        if state.status in ("completed", "failed", "cancelled"):
            return False

        state.cancelled = True
        state.status = "cancelled"
        state.finished_at = datetime.now(UTC)
        state.logs.append(f"[{datetime.now(UTC).isoformat()}] Run cancelled by user")

        return True

    async def get_logs(self, orchestrator_run_id: str) -> str:
        """Get execution logs for a run."""
        state = self._runs.get(orchestrator_run_id)
        if not state:
            return "Run not found"

        return "\n".join(state.logs)

    async def _execute_run(self, local_run_id: str) -> None:
        """Execute a run's DAG in topological order."""
        state = self._runs.get(local_run_id)
        if not state:
            return

        state.status = "running"
        state.started_at = datetime.now(UTC)
        state.logs.append(f"[{state.started_at.isoformat()}] Run started")

        try:
            # Reconstruct graph from flow definition
            graph = DependencyGraph.from_dict(state.flow_definition)

            # Get execution order (batches of nodes that can run in parallel)
            batches = graph.get_execution_order()

            state.logs.append(
                f"[{datetime.now(UTC).isoformat()}] Executing {len(graph.nodes)} nodes in {len(batches)} batches"
            )

            for batch_idx, batch in enumerate(batches):
                if state.cancelled:
                    break

                state.logs.append(
                    f"[{datetime.now(UTC).isoformat()}] Starting batch {batch_idx + 1}/{len(batches)}: {batch}"
                )

                # Execute batch in parallel
                tasks = [
                    self._execute_node(local_run_id, node_id, graph)
                    for node_id in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Check for failures
                for node_id, result in zip(batch, results):
                    if isinstance(result, Exception):
                        state.status = "failed"
                        state.error_message = f"Node {node_id} failed: {result}"
                        state.node_errors[node_id] = str(result)
                        state.logs.append(
                            f"[{datetime.now(UTC).isoformat()}] Node {node_id} FAILED: {result}"
                        )
                        state.finished_at = datetime.now(UTC)
                        return
                    else:
                        state.node_results[node_id] = result
                        state.logs.append(
                            f"[{datetime.now(UTC).isoformat()}] Node {node_id} completed"
                        )

            if state.cancelled:
                state.logs.append(
                    f"[{datetime.now(UTC).isoformat()}] Run was cancelled during execution"
                )
                return

            state.status = "completed"
            state.finished_at = datetime.now(UTC)
            state.logs.append(
                f"[{state.finished_at.isoformat()}] Run completed successfully"
            )

            # Aggregate metrics
            state.metrics = {
                "nodes_executed": len(state.node_results),
                "duration_seconds": (
                    state.finished_at - state.started_at
                ).total_seconds(),
            }

        except Exception as e:
            state.status = "failed"
            state.error_message = str(e)
            state.finished_at = datetime.now(UTC)
            state.logs.append(f"[{state.finished_at.isoformat()}] Run failed: {e}")
            logger.exception(f"Run {local_run_id} failed: {e}")

    async def _execute_node(
        self,
        local_run_id: str,
        node_id: str,
        graph: DependencyGraph,
    ) -> dict[str, Any]:
        """Execute a single node in the DAG."""
        state = self._runs.get(local_run_id)
        if not state:
            raise RuntimeError("Run state not found")

        node = graph.nodes.get(node_id)
        if not node:
            raise RuntimeError(f"Node {node_id} not found in graph")

        # Execute node using configured executor
        result = await self._node_executor(
            node_id=node_id,
            node_type=node.type,
            code_ref=node.data.code_ref,
            config={**node.data.config, **state.config},
        )

        return result

    async def _default_node_executor(
        self,
        node_id: str,
        node_type: str,
        code_ref: Optional[str],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Default node executor using libs.data.registry.

        Imports pipeline factories and executes the appropriate pipeline.
        This is run in a thread pool to avoid blocking the event loop.
        """
        loop = asyncio.get_event_loop()

        def execute() -> dict[str, Any]:
            # Import inside thread to avoid pickle issues (same pattern as optaic-v0)
            from libs.data.registry import PIPELINE_FACTORY

            if not code_ref:
                logger.warning(f"Node {node_id} has no code_ref, skipping")
                return {"status": "skipped", "reason": "no code_ref"}

            # Build and run pipeline
            try:
                pipeline = PIPELINE_FACTORY.build(code_ref, config=config)
                mode = config.get("mode", "overwrite")
                result = pipeline.run(mode=mode)

                return {
                    "status": "success",
                    "rows_processed": getattr(result, "row_count", None),
                    "last_data_date": getattr(result, "last_date", None),
                }
            except KeyError:
                # Pipeline not registered, log warning
                logger.warning(
                    f"Pipeline {code_ref} not registered in PIPELINE_FACTORY"
                )
                return {
                    "status": "skipped",
                    "reason": f"Pipeline {code_ref} not registered",
                }

        return await loop.run_in_executor(self._executor, execute)

    def cleanup(self) -> None:
        """Cleanup resources. Call when shutting down."""
        self._executor.shutdown(wait=False)
        self._runs.clear()
