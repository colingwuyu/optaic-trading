"""ExperimentRun Service - Expression Preview API.

This service provides the expression preview API for ExperimentRun resources:
1. Evaluate expressions with PIT date filtering
2. Create ExperimentRun records in the database
3. Capture input dataset versions for lineage
4. Return preview results (first N rows)

Phase 2.8c: ExperimentRun service for expression preview.

Key insight: ExperimentRuns are lightweight "preview" executions that:
- Don't persist to a Store (output is ephemeral)
- Support PIT date filtering for backtesting validation
- Track input versions for reproducibility
- Return preview data inline in the response
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.db.models.quant import DatasetInstance, ExperimentInstance, ExperimentRun
from libs.db.models.resource import Resource
from libs.orchestration import StatusStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.core.rbac.models import ActorContext
    from libs.orchestration import OrchestratorAdapter
    from optaic.guardrails.runtime.engine import GuardrailsEngine

logger = logging.getLogger(__name__)


class ExperimentRunService:
    """Service for expression preview execution.

    Provides a preview API for evaluating expressions against datasets
    with optional PIT date filtering.

    Example usage:
        service = ExperimentRunService(
            orchestrator=LocalOrchestrator(),
            status_store=StatusStore(session),
        )

        # Submit preview with date filter
        run = await service.submit_preview(
            session=session,
            actor=actor,
            experiment_id=experiment.id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            as_of_date=date(2024, 6, 30),  # PIT filter
            limit=100,
        )

        # Poll for results
        run = await service.poll_and_sync(session, run["id"])
    """

    def __init__(
        self,
        orchestrator: "OrchestratorAdapter",
        status_store: StatusStore,
        guardrails_engine: Optional["GuardrailsEngine"] = None,
    ) -> None:
        """Initialize ExperimentRunService.

        Args:
            orchestrator: Orchestration backend (Local, Prefect, etc.)
            status_store: Status storage for execution metadata
            guardrails_engine: Optional guardrails engine for validation
        """
        self._orchestrator = orchestrator
        self._status_store = status_store
        self._guardrails_engine = guardrails_engine

    async def submit_preview(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        experiment_id: UUID,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        as_of_date: Optional[date] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Submit an expression preview run.

        Args:
            session: Database session
            actor: Actor context for RBAC
            experiment_id: ExperimentInstance resource ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            as_of_date: Point-in-time date (what was known as of this date)
            limit: Maximum rows to return in preview

        Returns:
            Dict with run information including:
            - id: ExperimentRun resource ID
            - orchestrator_run_id: External run ID
            - status: Initial status ("running")

        Raises:
            ValueError: If experiment is not found
        """
        # 1. Load ExperimentInstance
        experiment = await session.get(ExperimentInstance, experiment_id)
        if not experiment or experiment.tenant_id != actor.tenant_id:
            raise ValueError(f"ExperimentInstance {experiment_id} not found")

        resource = await session.get(Resource, experiment_id)
        if not resource:
            raise ValueError(f"Experiment resource {experiment_id} not found")

        # 2. Capture input versions for lineage
        input_versions = await self._capture_input_versions(
            session, experiment.input_datasets_json
        )

        # 3. Create ExperimentRun resource
        run_id = uuid4()
        run_resource = Resource(
            id=run_id,
            tenant_id=actor.tenant_id,
            type="ExperimentRun",
            parent_id=experiment_id,
            name=f"Experiment run for {resource.name}",
            owner_principal_id=actor.id,
            status="active",
        )
        session.add(run_resource)

        # 4. Create ExperimentRun extension
        experiment_run = ExperimentRun(
            resource_id=run_id,
            tenant_id=actor.tenant_id,
            experiment_instance_id=experiment_id,
            expression_text=experiment.expression_text,
            input_versions_json=input_versions,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            status="queued",
        )
        session.add(experiment_run)
        await session.flush()

        # 5. Validate via GuardrailsEngine (if configured)
        if self._guardrails_engine:
            await self._validate_at_gate(
                session=session,
                actor=actor,
                resource_id=experiment_id,
                run_id=run_id,
                target_snapshot={
                    "expression": experiment.expression_text,
                    "start_date": str(start_date) if start_date else None,
                    "end_date": str(end_date) if end_date else None,
                    "as_of_date": str(as_of_date) if as_of_date else None,
                    "limit": limit,
                    "input_versions": input_versions,
                },
            )

        # 6. Build flow definition for expression evaluation
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
                        "start_date": str(start_date) if start_date else None,
                        "end_date": str(end_date) if end_date else None,
                        "as_of_date": str(as_of_date) if as_of_date else None,
                        "limit": limit,
                    },
                    "status": "pending",
                }
            ],
            "edges": [],
        }

        config = {
            "mode": "preview",
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
            "as_of_date": str(as_of_date) if as_of_date else None,
            "limit": limit,
        }

        tags = {
            "tenant_id": str(actor.tenant_id),
            "actor_id": str(actor.id),
            "run_type": "experiment",
            "experiment_id": str(experiment_id),
        }

        # 7. Submit to orchestrator
        result = await self._orchestrator.submit_run(
            run_id=run_id,
            flow_definition=flow_definition,
            config=config,
            tags=tags,
        )

        # 8. Update ExperimentRun with orchestrator info
        experiment_run.orchestrator_kind = result.orchestrator_kind
        experiment_run.orchestrator_run_id = result.orchestrator_run_id
        experiment_run.status = "running"
        experiment_run.started_at = datetime.now(UTC)

        # 9. Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=run_id,
            resource_type="ExperimentRun",
            action="experiment.run_started",
            payload={
                "experiment_id": str(experiment_id),
                "expression": experiment.expression_text,
                "orchestrator_run_id": result.orchestrator_run_id,
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None,
                "as_of_date": str(as_of_date) if as_of_date else None,
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(run_id),
            "experiment_id": str(experiment_id),
            "expression": experiment.expression_text,
            "orchestrator_run_id": result.orchestrator_run_id,
            "orchestrator_kind": result.orchestrator_kind,
            "status": "running",
            "started_at": experiment_run.started_at.isoformat(),
        }

    async def poll_and_sync(
        self,
        session: "AsyncSession",
        run_id: UUID,
    ) -> dict[str, Any]:
        """Poll orchestrator and sync status to ExperimentRun.

        Args:
            session: Database session
            run_id: ExperimentRun resource ID

        Returns:
            Updated run information with results if completed
        """
        # Load ExperimentRun
        experiment_run = await session.get(ExperimentRun, run_id)
        if not experiment_run:
            raise ValueError(f"ExperimentRun {run_id} not found")

        resource = await session.get(Resource, run_id)

        # Skip if already in terminal state
        if experiment_run.status in ("completed", "failed", "cancelled"):
            return self._run_to_dict(experiment_run, resource)

        # Get orchestrator run ID
        if not experiment_run.orchestrator_run_id:
            raise ValueError(f"ExperimentRun {run_id} has no orchestrator_run_id")

        # Poll orchestrator
        status = await self._orchestrator.get_status(experiment_run.orchestrator_run_id)

        # Update if status changed
        if status.status != experiment_run.status:
            old_status = experiment_run.status
            experiment_run.status = status.status
            experiment_run.finished_at = status.finished_at

            # Extract results if available
            if status.metrics:
                experiment_run.result_columns = status.metrics.get("columns")
                experiment_run.row_count = status.metrics.get("row_count")
                experiment_run.result_preview_json = status.metrics.get("preview_data")

            await session.commit()

            logger.info(
                f"ExperimentRun {run_id} status changed: {old_status} -> {status.status}"
            )

            # Emit completion activity
            if status.status in ("completed", "failed"):
                await self._emit_completion_activity(
                    session,
                    experiment_run,
                    status.status,
                    status.error_message,
                )

        return self._run_to_dict(experiment_run, resource)

    async def get_results(
        self,
        session: "AsyncSession",
        run_id: UUID,
    ) -> dict[str, Any]:
        """Get preview results for a completed experiment run.

        Args:
            session: Database session
            run_id: ExperimentRun resource ID

        Returns:
            Preview results including columns, data, and row count
        """
        experiment_run = await session.get(ExperimentRun, run_id)
        if not experiment_run:
            raise ValueError(f"ExperimentRun {run_id} not found")

        if experiment_run.status != "completed":
            return {
                "id": str(run_id),
                "status": experiment_run.status,
                "message": "Results not available yet",
            }

        return {
            "id": str(run_id),
            "status": "completed",
            "expression": experiment_run.expression_text,
            "columns": experiment_run.result_columns,
            "row_count": experiment_run.row_count,
            "preview_data": experiment_run.result_preview_json,
            "start_date": str(experiment_run.start_date)
            if experiment_run.start_date
            else None,
            "end_date": str(experiment_run.end_date)
            if experiment_run.end_date
            else None,
            "as_of_date": str(experiment_run.as_of_date)
            if experiment_run.as_of_date
            else None,
        }

    async def cancel_run(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        run_id: UUID,
    ) -> dict[str, Any]:
        """Cancel a running experiment.

        Args:
            session: Database session
            actor: Actor context for RBAC
            run_id: ExperimentRun resource ID

        Returns:
            Updated run information
        """
        experiment_run = await session.get(ExperimentRun, run_id)
        if not experiment_run or experiment_run.tenant_id != actor.tenant_id:
            raise ValueError(f"ExperimentRun {run_id} not found")

        if not experiment_run.orchestrator_run_id:
            raise ValueError(f"ExperimentRun {run_id} has no orchestrator_run_id")

        # Cancel in orchestrator
        success = await self._orchestrator.cancel_run(
            experiment_run.orchestrator_run_id
        )

        if success:
            experiment_run.status = "cancelled"
            experiment_run.finished_at = datetime.now(UTC)
            await session.commit()

            # Emit activity
            envelope = ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=run_id,
                resource_type="ExperimentRun",
                action="experiment.run_cancelled",
                payload={
                    "experiment_id": str(experiment_run.experiment_instance_id),
                    "orchestrator_run_id": experiment_run.orchestrator_run_id,
                },
            )
            await record_activity_with_outbox(session, envelope)
            await session.commit()

        resource = await session.get(Resource, run_id)
        return self._run_to_dict(experiment_run, resource)

    async def list_runs(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        *,
        experiment_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List experiment runs with optional filters.

        Args:
            session: Database session
            actor: Actor context
            experiment_id: Filter by experiment
            status: Filter by status
            limit: Maximum results

        Returns:
            List of experiment run info
        """
        from sqlalchemy import select

        stmt = (
            select(Resource, ExperimentRun)
            .join(ExperimentRun, Resource.id == ExperimentRun.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "ExperimentRun",
            )
        )

        if experiment_id:
            stmt = stmt.where(ExperimentRun.experiment_instance_id == experiment_id)

        if status:
            stmt = stmt.where(ExperimentRun.status == status)

        stmt = stmt.order_by(ExperimentRun.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [self._run_to_dict(run, resource) for resource, run in rows]

    async def _capture_input_versions(
        self,
        session: "AsyncSession",
        input_datasets: dict[str, Any],
    ) -> dict[str, Any]:
        """Capture versions of input datasets for lineage tracking."""
        input_versions = {}

        for alias, dataset_id_str in input_datasets.items():
            try:
                dataset_id = UUID(dataset_id_str)
                status_record = await self._status_store.get_status(dataset_id)

                # Also get DatasetInstance for freshness info
                dataset = await session.get(DatasetInstance, dataset_id)

                input_versions[alias] = {
                    "dataset_id": dataset_id_str,
                    "last_data_date": (
                        str(status_record.last_data_date)
                        if status_record and status_record.last_data_date
                        else None
                    ),
                    "freshness_status": (
                        dataset.freshness_status if dataset else "unknown"
                    ),
                    "last_refresh_at": (
                        dataset.last_refresh_at.isoformat()
                        if dataset and dataset.last_refresh_at
                        else None
                    ),
                }
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not capture version for {alias}: {e}")
                input_versions[alias] = {
                    "dataset_id": dataset_id_str,
                    "error": str(e),
                }

        return input_versions

    async def _validate_at_gate(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        resource_id: UUID,
        run_id: UUID,
        target_snapshot: dict[str, Any],
    ) -> None:
        """Validate via GuardrailsEngine at run creation gate."""
        if not self._guardrails_engine:
            return

        from optaic.guardrails.runtime.context import GuardrailsContext

        # Load resource to get space/subspace info
        resource = await session.get(Resource, resource_id)
        space_kind = getattr(resource, "space_kind", None)
        subspace_kind = getattr(resource, "subspace_kind", None)

        # Build context
        context = GuardrailsContext(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            space_kind=space_kind,
            subspace_kind=subspace_kind,
            action="run.create",
            extra={"run_type": "ExperimentRun"},
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

    async def _emit_completion_activity(
        self,
        session: "AsyncSession",
        experiment_run: ExperimentRun,
        status: str,
        error_message: Optional[str],
    ) -> None:
        """Emit activity for run completion."""
        action = (
            "experiment.run_completed"
            if status == "completed"
            else "experiment.run_failed"
        )

        payload = {
            "experiment_id": str(experiment_run.experiment_instance_id),
            "row_count": experiment_run.row_count,
        }
        if error_message:
            payload["error"] = error_message

        envelope = ActivityEnvelope(
            tenant_id=experiment_run.tenant_id,
            actor_principal_id=None,  # System event
            resource_id=experiment_run.resource_id,
            resource_type="ExperimentRun",
            action=action,
            payload=payload,
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

    def _run_to_dict(
        self, experiment_run: ExperimentRun, resource: Optional[Resource]
    ) -> dict[str, Any]:
        """Convert ExperimentRun to dict."""
        return {
            "id": str(experiment_run.resource_id),
            "type": "ExperimentRun",
            "name": resource.name if resource else None,
            "experiment_id": str(experiment_run.experiment_instance_id),
            "expression": experiment_run.expression_text,
            "status": experiment_run.status,
            "orchestrator_kind": experiment_run.orchestrator_kind,
            "orchestrator_run_id": experiment_run.orchestrator_run_id,
            "start_date": (
                str(experiment_run.start_date) if experiment_run.start_date else None
            ),
            "end_date": (
                str(experiment_run.end_date) if experiment_run.end_date else None
            ),
            "as_of_date": (
                str(experiment_run.as_of_date) if experiment_run.as_of_date else None
            ),
            "row_count": experiment_run.row_count,
            "result_columns": experiment_run.result_columns,
            "started_at": (
                experiment_run.started_at.isoformat()
                if experiment_run.started_at
                else None
            ),
            "finished_at": (
                experiment_run.finished_at.isoformat()
                if experiment_run.finished_at
                else None
            ),
            "created_at": experiment_run.created_at.isoformat(),
        }
