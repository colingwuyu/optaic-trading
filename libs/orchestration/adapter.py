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
class DeploymentResult:
    """Result of creating a deployment (Flow Execution Resource)."""

    deployment_id: str
    orchestrator_kind: str
    deployment_meta: dict[str, Any] = field(default_factory=dict)


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
        """Create a deployment (Flow Execution Resource) for an Instance.

        This creates a static Prefect deployment that can be triggered to create
        flow runs. The deployment is paired with the Instance and represents
        the execution capability.

        Args:
            instance_id: The Instance resource ID (for correlation)
            flow_name: Human-readable name for the deployment
            flow_template: Flow template to use (e.g., "dataset_refresh")
            parameters: Default parameters for the deployment
            schedule: Optional schedule configuration (cron, interval, etc.)
            tags: Correlation tags

        Returns:
            DeploymentResult with the deployment ID

        Note: Default implementation returns a fake deployment for non-Prefect backends.
        """
        # Default: Return a fake deployment ID for local/test environments
        return DeploymentResult(
            deployment_id=f"local-{instance_id}",
            orchestrator_kind=self.kind,
            deployment_meta={"flow_template": flow_template},
        )

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a deployment (cleanup when Instance is deleted).

        Args:
            deployment_id: The deployment ID to delete

        Returns:
            True if deletion was successful, False otherwise

        Note: Default implementation is a no-op for non-Prefect backends.
        """
        return True

    async def trigger_deployment(
        self,
        deployment_id: str,
        run_id: UUID,
        parameters: Optional[dict[str, Any]] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> SubmitResult:
        """Trigger a run on an existing deployment.

        This creates a new flow run under the existing deployment, which is
        the preferred way to execute Instances that have deployments.

        Args:
            deployment_id: The deployment to trigger
            run_id: The Run resource ID (for correlation)
            parameters: Override parameters for this run
            tags: Additional tags for this run

        Returns:
            SubmitResult with the flow run ID

        Note: Default implementation creates a local run for non-Prefect backends.
        """
        # Default: Use submit_run with an empty flow definition
        return await self.submit_run(
            run_id=run_id,
            flow_definition={"nodes": [], "edges": []},
            config=parameters or {},
            tags=tags or {},
        )
