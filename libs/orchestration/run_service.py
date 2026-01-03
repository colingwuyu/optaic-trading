"""RunExecutionService - Central execution coordinator.

Coordinates execution of Run resources by:
1. Creating Run resources (governance layer)
2. Validating via GuardrailsEngine at lifecycle gates
3. Building flow definitions from dependency graphs
4. Submitting to orchestrator (Local or Prefect)
5. Polling and syncing status
6. Updating Instance state on completion
7. Emitting activity events for audit trails

This is the foundational service that all concrete Run types
(PipelineRun, ExperimentRun, BacktestRun, etc.) build upon.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from .adapter import OrchestratorAdapter, RunStatus
from .dag import build_graph
from .status_store import StatusStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.core.rbac.models import ActorContext
    from libs.db.models import Resource
    from optaic.guardrails.runtime.engine import GuardrailsEngine

logger = logging.getLogger(__name__)


class RunExecutionService:
    """High-level service for executing runs with governance integration.

    Provides a unified interface for executing any type of run:
    - Pipeline runs (dataset refresh)
    - Experiment runs (expression preview)
    - Backtest runs (strategy evaluation)
    - Training runs (ML model training)
    - Inference runs (ML predictions)

    The service handles:
    - Creating Run resources with proper governance (parent reference, RBAC)
    - Building dependency graphs from Instance resources
    - Submitting to the configured orchestrator
    - Polling and syncing status back to Run resources
    - Updating parent Instance state on completion
    - Emitting ActivityEnvelope for audit trails

    Example usage:
        service = RunExecutionService(
            orchestrator=LocalOrchestrator(),
            status_store=StatusStore(session),
        )

        # Submit a pipeline run
        run = await service.submit_pipeline_run(
            session=session,
            actor=actor,
            dataset_id=dataset.id,
            mode="incremental",
        )

        # Poll for completion
        run = await service.poll_and_sync(session, run.id)
    """

    def __init__(
        self,
        orchestrator: OrchestratorAdapter,
        status_store: StatusStore,
        guardrails_engine: Optional["GuardrailsEngine"] = None,
    ) -> None:
        """Initialize RunExecutionService.

        Args:
            orchestrator: Orchestration backend (Local, Prefect, etc.)
            status_store: Status storage for execution metadata
            guardrails_engine: Optional guardrails engine for validation at gates
        """
        self._orchestrator = orchestrator
        self._status_store = status_store
        self._guardrails_engine = guardrails_engine

    @property
    def orchestrator(self) -> OrchestratorAdapter:
        """Get the configured orchestrator."""
        return self._orchestrator

    @property
    def status_store(self) -> StatusStore:
        """Get the status store."""
        return self._status_store

    @property
    def guardrails_engine(self) -> Optional["GuardrailsEngine"]:
        """Get the guardrails engine (if configured)."""
        return self._guardrails_engine

    async def submit_pipeline_run(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        dataset_id: UUID,
        *,
        mode: str = "incremental",
        force: bool = False,
    ) -> dict[str, Any]:
        """Submit a pipeline run for a dataset.

        Args:
            session: Database session
            actor: Actor context for RBAC
            dataset_id: Dataset instance resource ID
            mode: Execution mode - "overwrite" or "incremental"
            force: Force run even if dataset is fresh

        Returns:
            Dict with run information including:
            - id: Run resource ID
            - orchestrator_run_id: External run ID
            - status: Initial status ("running")

        Raises:
            ValueError: If dataset is already fresh and force=False
        """
        from libs.db.models.resource import Resource
        from libs.db.models.quant import DatasetInstance

        # 1. Check if refresh needed (unless forced)
        if not force:
            status = await self._status_store.get_status(dataset_id)
            if status and status.last_pipeline_status == "success":
                dataset = await session.get(DatasetInstance, dataset_id)
                if dataset and dataset.freshness_status == "fresh":
                    raise ValueError(
                        "Dataset is already fresh. Use force=True to override."
                    )

        # 2. Load dataset resource
        resource = await session.get(Resource, dataset_id)
        if not resource:
            raise ValueError(f"Dataset resource {dataset_id} not found")

        # 3. Build dependency graph
        graph = await build_graph(
            session=session,
            root_id=dataset_id,
            tenant_id=actor.tenant_id,
            include_status=True,
        )

        # 4. Validate via GuardrailsEngine (if configured)
        run_id = uuid4()
        if self._guardrails_engine:
            await self._validate_at_gate(
                session=session,
                actor=actor,
                resource_id=dataset_id,
                run_id=run_id,
                run_type="PipelineRun",
                action="run.create",
                target_snapshot={
                    "mode": mode,
                    "nodes": len(graph.nodes),
                    "edges": len(graph.edges),
                },
            )

        # 5. Create Run resource
        run_resource = Resource(
            id=run_id,
            tenant_id=actor.tenant_id,
            type="PipelineRun",
            parent_id=dataset_id,
            name=f"Pipeline run for {resource.name}",
            owner_principal_id=actor.id,
        )
        session.add(run_resource)
        await session.flush()

        # 6. Mark run start in status store
        await self._status_store.mark_run_start(dataset_id)

        # 7. Submit to orchestrator
        flow_definition = graph.to_dict()
        config = {"mode": mode}
        tags = {
            "tenant_id": str(actor.tenant_id),
            "actor_id": str(actor.id),
            "run_type": "pipeline",
            "dataset_id": str(dataset_id),
        }

        result = await self._orchestrator.submit_run(
            run_id=run_id,
            flow_definition=flow_definition,
            config=config,
            tags=tags,
        )

        # 8. Store orchestrator info in resource metadata
        run_resource.metadata_json = {
            "orchestrator_kind": result.orchestrator_kind,
            "orchestrator_run_id": result.orchestrator_run_id,
            "orchestrator_meta": result.orchestrator_meta,
            "mode": mode,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "running",
        }
        await session.commit()

        # 9. Emit activity (async, non-blocking)
        await self._emit_activity(
            session=session,
            actor=actor,
            action="pipeline.run_started",
            resource_id=run_id,
            payload={
                "dataset_id": str(dataset_id),
                "mode": mode,
                "orchestrator_run_id": result.orchestrator_run_id,
                "nodes": len(graph.nodes),
            },
        )

        return {
            "id": str(run_id),
            "dataset_id": str(dataset_id),
            "orchestrator_run_id": result.orchestrator_run_id,
            "orchestrator_kind": result.orchestrator_kind,
            "mode": mode,
            "status": "running",
            "nodes": len(graph.nodes),
        }

    async def submit_experiment_run(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        experiment_id: UUID,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        as_of_date: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Submit an experiment run (expression preview).

        Args:
            session: Database session
            actor: Actor context for RBAC
            experiment_id: Experiment instance resource ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            as_of_date: Optional PIT date
            limit: Maximum rows to return

        Returns:
            Dict with run information
        """
        from libs.db.models.resource import Resource
        from libs.db.models.quant import ExperimentInstance

        # 1. Load experiment
        experiment = await session.get(ExperimentInstance, experiment_id)
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        resource = await session.get(Resource, experiment_id)
        if not resource:
            raise ValueError(f"Experiment resource {experiment_id} not found")

        # 2. Validate via GuardrailsEngine (if configured)
        run_id = uuid4()
        if self._guardrails_engine:
            await self._validate_at_gate(
                session=session,
                actor=actor,
                resource_id=experiment_id,
                run_id=run_id,
                run_type="ExperimentRun",
                action="run.create",
                target_snapshot={
                    "expression": experiment.expression_text,
                    "start_date": start_date,
                    "end_date": end_date,
                    "as_of_date": as_of_date,
                    "limit": limit,
                },
            )

        # 3. Create Run resource
        run_resource = Resource(
            id=run_id,
            tenant_id=actor.tenant_id,
            type="ExperimentRun",
            parent_id=experiment_id,
            name=f"Experiment run for {resource.name}",
            owner_principal_id=actor.id,
        )
        session.add(run_resource)

        # 4. Build simple flow (expression evaluation doesn't need DAG)
        flow_definition = {
            "nodes": [
                {
                    "id": str(experiment_id),
                    "label": resource.name,
                    "type": "expression",
                    "resource_id": str(experiment_id),
                    "code_ref": "ExpressionEvaluator",
                    "config": {
                        "expression": experiment.expression_text,
                        "input_datasets": experiment.input_datasets_json,
                        "start_date": start_date,
                        "end_date": end_date,
                        "as_of_date": as_of_date,
                        "limit": limit,
                    },
                    "status": "pending",
                }
            ],
            "edges": [],
        }

        config = {
            "mode": "preview",
            "start_date": start_date,
            "end_date": end_date,
            "as_of_date": as_of_date,
            "limit": limit,
        }

        tags = {
            "tenant_id": str(actor.tenant_id),
            "actor_id": str(actor.id),
            "run_type": "experiment",
            "experiment_id": str(experiment_id),
        }

        # 5. Submit to orchestrator
        result = await self._orchestrator.submit_run(
            run_id=run_id,
            flow_definition=flow_definition,
            config=config,
            tags=tags,
        )

        # 6. Store orchestrator info
        run_resource.metadata_json = {
            "orchestrator_kind": result.orchestrator_kind,
            "orchestrator_run_id": result.orchestrator_run_id,
            "expression": experiment.expression_text,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "running",
        }
        await session.commit()

        # 7. Emit activity
        await self._emit_activity(
            session=session,
            actor=actor,
            action="experiment.run_started",
            resource_id=run_id,
            payload={
                "experiment_id": str(experiment_id),
                "expression": experiment.expression_text,
                "orchestrator_run_id": result.orchestrator_run_id,
            },
        )

        return {
            "id": str(run_id),
            "experiment_id": str(experiment_id),
            "orchestrator_run_id": result.orchestrator_run_id,
            "orchestrator_kind": result.orchestrator_kind,
            "status": "running",
        }

    async def poll_and_sync(
        self,
        session: "AsyncSession",
        run_id: UUID,
    ) -> dict[str, Any]:
        """Poll orchestrator and sync status to Run resource.

        Args:
            session: Database session
            run_id: Run resource ID

        Returns:
            Updated run information
        """
        from libs.db.models.resource import Resource

        # Load run resource
        run = await session.get(Resource, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        metadata = run.metadata_json or {}
        current_status = metadata.get("status", "unknown")

        # Skip if already in terminal state
        if current_status in ("completed", "failed", "cancelled"):
            return self._run_to_dict(run)

        # Get orchestrator run ID
        orchestrator_run_id = metadata.get("orchestrator_run_id")
        if not orchestrator_run_id:
            raise ValueError(f"Run {run_id} has no orchestrator_run_id")

        # Poll orchestrator
        status = await self._orchestrator.get_status(orchestrator_run_id)

        # Update if status changed
        if status.status != current_status:
            metadata["status"] = status.status
            metadata["finished_at"] = (
                status.finished_at.isoformat() if status.finished_at else None
            )
            metadata["error_message"] = status.error_message
            metadata["metrics"] = status.metrics

            run.metadata_json = metadata
            await session.commit()

            # Handle completion
            if status.status == "completed":
                await self._on_run_completed(session, run, status)
            elif status.status == "failed":
                await self._on_run_failed(session, run, status)

        return self._run_to_dict(run)

    async def cancel_run(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        run_id: UUID,
    ) -> dict[str, Any]:
        """Cancel a running execution.

        Args:
            session: Database session
            actor: Actor context for RBAC
            run_id: Run resource ID

        Returns:
            Updated run information
        """
        from libs.db.models.resource import Resource

        run = await session.get(Resource, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        metadata = run.metadata_json or {}
        orchestrator_run_id = metadata.get("orchestrator_run_id")

        if not orchestrator_run_id:
            raise ValueError(f"Run {run_id} has no orchestrator_run_id")

        # Cancel in orchestrator
        success = await self._orchestrator.cancel_run(orchestrator_run_id)

        if success:
            metadata["status"] = "cancelled"
            metadata["finished_at"] = datetime.now(UTC).isoformat()
            run.metadata_json = metadata
            await session.commit()

            # Emit activity
            await self._emit_activity(
                session=session,
                actor=actor,
                action=f"{run.type.lower()}.run_cancelled",
                resource_id=run_id,
                payload={"orchestrator_run_id": orchestrator_run_id},
            )

        return self._run_to_dict(run)

    async def get_logs(
        self,
        session: "AsyncSession",
        run_id: UUID,
    ) -> str:
        """Get execution logs for a run.

        Args:
            session: Database session
            run_id: Run resource ID

        Returns:
            Log output as string
        """
        from libs.db.models.resource import Resource

        run = await session.get(Resource, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        metadata = run.metadata_json or {}
        orchestrator_run_id = metadata.get("orchestrator_run_id")

        if not orchestrator_run_id:
            return "No orchestrator run ID"

        return await self._orchestrator.get_logs(orchestrator_run_id)

    async def _on_run_completed(
        self,
        session: "AsyncSession",
        run: "Resource",
        status: RunStatus,
    ) -> None:
        """Handle successful run completion."""
        from libs.db.models.quant import DatasetInstance

        # Update parent instance state based on run type
        if run.type == "PipelineRun" and run.parent_id:
            dataset = await session.get(DatasetInstance, run.parent_id)
            if dataset:
                dataset.freshness_status = "fresh"
                dataset.last_refresh_at = datetime.now(UTC)

                # Update status store
                metrics = status.metrics or {}
                await self._status_store.mark_run_success(
                    dataset_id=run.parent_id,
                    last_data_date=metrics.get("last_data_date"),
                    rows_processed=metrics.get("rows_processed"),
                )

        await session.commit()

        # Emit completion activity
        await self._emit_activity(
            session=session,
            actor=None,  # System event
            action=f"{run.type.lower()}.run_completed",
            resource_id=run.id,
            payload={"metrics": status.metrics},
        )

    async def _on_run_failed(
        self,
        session: "AsyncSession",
        run: "Resource",
        status: RunStatus,
    ) -> None:
        """Handle run failure."""
        # Update status store with error
        if run.type == "PipelineRun" and run.parent_id:
            await self._status_store.mark_run_error(
                dataset_id=run.parent_id,
                error_message=status.error_message or "Unknown error",
            )

        await session.commit()

        # Emit failure activity
        await self._emit_activity(
            session=session,
            actor=None,  # System event
            action=f"{run.type.lower()}.run_failed",
            resource_id=run.id,
            payload={"error": status.error_message},
        )

    async def _emit_activity(
        self,
        session: "AsyncSession",
        actor: Optional["ActorContext"],
        action: str,
        resource_id: UUID,
        payload: dict[str, Any],
    ) -> None:
        """Emit an activity event (via outbox pattern)."""
        from libs.db.models.activity import Activity, Outbox

        activity = Activity(
            id=uuid4(),
            tenant_id=actor.tenant_id if actor else None,
            resource_id=resource_id,
            action=action,
            actor_principal_id=actor.id if actor else None,
            payload=payload,
        )
        session.add(activity)

        # Queue for async processing
        outbox = Outbox(
            id=uuid4(),
            payload={
                "activity_id": str(activity.id),
                "action": action,
                "resource_id": str(resource_id),
                "payload": payload,
            },
        )
        session.add(outbox)

    async def _validate_at_gate(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        resource_id: UUID,
        run_id: UUID,
        run_type: str,
        action: str,
        target_snapshot: dict[str, Any],
    ) -> None:
        """Validate via GuardrailsEngine at a lifecycle gate.

        Args:
            session: Database session
            actor: Actor context for RBAC
            resource_id: Parent resource being executed
            run_id: The run ID being created
            run_type: Type of run (PipelineRun, ExperimentRun, etc.)
            action: Action being performed (e.g., "run.create")
            target_snapshot: Data snapshot to validate

        Raises:
            GuardrailsBlocked: If validation fails and enforcement is "block"
        """
        from optaic.guardrails.runtime.context import GuardrailsContext

        if not self._guardrails_engine:
            return

        # Load resource to get space/subspace info
        from libs.db.models.resource import Resource

        resource = await session.get(Resource, resource_id)
        space_kind = None
        subspace_kind = None
        if resource:
            metadata = resource.metadata_json or {}
            space_kind = metadata.get("space_kind")
            subspace_kind = metadata.get("subspace_kind")

        # Build context
        context = GuardrailsContext(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            space_kind=space_kind,
            subspace_kind=subspace_kind,
            action=action,
            extra={"run_type": run_type},
        )

        # Validate at gate - will raise GuardrailsBlocked if blocked
        await self._guardrails_engine.validate_at_gate(
            db=session,
            scope="run",
            target_id=str(run_id),
            resource_id=str(resource_id),
            context=context,
            target_snapshot=target_snapshot,
        )

    def _run_to_dict(self, run: "Resource") -> dict[str, Any]:
        """Convert run resource to dict."""
        metadata = run.metadata_json or {}
        return {
            "id": str(run.id),
            "type": run.type,
            "parent_id": str(run.parent_id) if run.parent_id else None,
            "name": run.name,
            "status": metadata.get("status", "unknown"),
            "orchestrator_kind": metadata.get("orchestrator_kind"),
            "orchestrator_run_id": metadata.get("orchestrator_run_id"),
            "started_at": metadata.get("started_at"),
            "finished_at": metadata.get("finished_at"),
            "error_message": metadata.get("error_message"),
            "metrics": metadata.get("metrics"),
        }
