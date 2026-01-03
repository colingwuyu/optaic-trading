"""OrchestratorAdapter abstract interface.

Defines the contract for execution orchestration backends.
Implementations include:
- LocalOrchestrator: In-process DAG executor (testing, embedded)
- PrefectOrchestrator: Prefect server integration (production)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID


@dataclass
class SubmitResult:
    """Result of submitting a run to an orchestrator."""

    orchestrator_run_id: str
    orchestrator_kind: str
    orchestrator_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunStatus:
    """Current status of a run in the orchestrator."""

    status: str  # "queued", "running", "completed", "failed", "cancelled"
    error_message: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class OrchestratorAdapter(ABC):
    """Abstract interface for execution orchestration.

    All orchestration backends must implement this interface to provide
    a consistent API for submitting, monitoring, and cancelling runs.

    Implementations:
    - LocalOrchestrator: In-process execution using ThreadPoolExecutor
    - PrefectOrchestrator: Prefect server API integration
    - (Future) AirflowOrchestrator: Airflow DAG submission

    Example usage:
        orchestrator = LocalOrchestrator(max_workers=4)

        result = await orchestrator.submit_run(
            run_id=run.id,
            flow_definition={"nodes": [...], "edges": [...]},
            config={"mode": "incremental"},
            tags={"tenant_id": str(tenant_id)},
        )

        status = await orchestrator.get_status(result.orchestrator_run_id)
    """

    @property
    @abstractmethod
    def kind(self) -> str:
        """Return the orchestrator kind identifier.

        Returns:
            One of: 'local', 'prefect', 'airflow', etc.
        """
        pass

    @abstractmethod
    async def submit_run(
        self,
        run_id: UUID,
        flow_definition: dict[str, Any],
        config: dict[str, Any],
        tags: dict[str, str],
    ) -> SubmitResult:
        """Submit a run to the orchestrator.

        Args:
            run_id: The Run resource ID (for correlation)
            flow_definition: DAG specification with nodes and edges
                {
                    "nodes": [
                        {"id": "node1", "type": "pipeline", "code_ref": "..."},
                        {"id": "node2", "type": "expression", "expression": "..."},
                    ],
                    "edges": [
                        {"source": "node1", "target": "node2"},
                    ],
                }
            config: Input parameters for execution
                {
                    "mode": "overwrite" | "incremental",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                }
            tags: Correlation tags for tracking
                {
                    "tenant_id": "...",
                    "actor_id": "...",
                    "run_type": "pipeline",
                }

        Returns:
            SubmitResult with orchestrator's external run ID
        """
        pass

    @abstractmethod
    async def get_status(self, orchestrator_run_id: str) -> RunStatus:
        """Get current status of a run from the orchestrator.

        Args:
            orchestrator_run_id: The external run ID from submit_run()

        Returns:
            RunStatus with current status, timing, and any errors
        """
        pass

    @abstractmethod
    async def cancel_run(self, orchestrator_run_id: str) -> bool:
        """Cancel a running execution.

        Args:
            orchestrator_run_id: The external run ID to cancel

        Returns:
            True if cancellation was successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_logs(self, orchestrator_run_id: str) -> str:
        """Get execution logs for a run.

        Args:
            orchestrator_run_id: The external run ID

        Returns:
            Log output as a string (may be truncated for large logs)
        """
        pass
