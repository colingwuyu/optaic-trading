"""PipelineRun Service - Lineage-Aware Pipeline Execution.

This service provides lineage-checking execution for PipelineRun resources:
1. Check upstream freshness via LineageResolver before execution
2. Block or warn if upstream dependencies are stale/error
3. Create PipelineRun records in the database
4. Trigger Prefect deployments (or submit runs directly)
5. Update StatusStore on completion
6. Propagate staleness to downstream resources

Phase 2.8b: Concrete Run resource type with lineage integration.

Key insight: Lineage is flow-to-flow, not instance-to-instance.
When checking if a pipeline can run, we check the freshness of
upstream DatasetInstances, not their definitions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.core.rbac.models import ActorContext
from libs.db.models.quant import DatasetInstance, PipelineRun
from libs.db.models.resource import Resource
from libs.orchestration import (
    CentrifugoNotifier,
    FreshnessChecker,
    LineageFreshnessReport,
    LineageObserver,
    LineageResolver,
    StatusStore,
    UpstreamNotReadyError,
)
from libs.orchestration.freshness import DatasetStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.core.rbac.models import ActorContext
    from libs.orchestration import OrchestratorAdapter
    from optaic.guardrails.runtime.engine import GuardrailsEngine

logger = logging.getLogger(__name__)


class PipelineRunService:
    """Service for lineage-aware pipeline run execution.

    Provides a higher-level API for executing PipelineRuns that:
    - Validates upstream freshness before execution
    - Creates PipelineRun records with lineage metadata
    - Uses Prefect deployments when available
    - Updates StatusStore and propagates staleness on completion

    Example usage:
        service = PipelineRunService(
            orchestrator=PrefectOrchestrator(),
            status_store=StatusStore(session),
        )

        # Submit with lineage checking (will block if upstreams are stale)
        run = await service.submit_run(
            session=session,
            actor=actor,
            dataset_id=dataset.id,
            mode="incremental",
        )

        # Force run even if upstreams are stale
        run = await service.submit_run(
            session=session,
            actor=actor,
            dataset_id=dataset.id,
            force=True,
        )

        # Poll for completion
        run = await service.poll_and_sync(session, run["id"])
    """

    def __init__(
        self,
        orchestrator: "OrchestratorAdapter",
        status_store: StatusStore,
        guardrails_engine: Optional["GuardrailsEngine"] = None,
    ) -> None:
        """Initialize PipelineRunService.

        Args:
            orchestrator: Orchestration backend (Local, Prefect, etc.)
            status_store: Status storage for execution metadata
            guardrails_engine: Optional guardrails engine for validation at gates
        """
        self._orchestrator = orchestrator
        self._status_store = status_store
        self._guardrails_engine = guardrails_engine
        self._lineage_resolver = LineageResolver()
        self._freshness_checker = FreshnessChecker(status_store)
        self._lineage_observer = LineageObserver()
        self._centrifugo_notifier = CentrifugoNotifier()

    async def submit_run(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        dataset_id: UUID,
        *,
        mode: str = "incremental",
        force: bool = False,
        warn_on_stale: bool = True,
    ) -> dict[str, Any]:
        """Submit a pipeline run with lineage checking.

        Args:
            session: Database session
            actor: Actor context for RBAC
            dataset_id: DatasetInstance resource ID
            mode: Execution mode - "overwrite" or "incremental"
            force: Force run even if upstreams are stale/error
            warn_on_stale: If force=True but upstreams are stale, include warning

        Returns:
            Dict with run information including:
            - id: PipelineRun resource ID
            - orchestrator_run_id: External run ID
            - status: Initial status ("running" or "queued")
            - upstream_warning: If force=True and upstreams were stale

        Raises:
            UpstreamNotReadyError: If upstreams are stale and force=False
            ValueError: If dataset is not found
        """
        # 1. Load DatasetInstance
        dataset = await session.get(DatasetInstance, dataset_id)
        if not dataset or dataset.tenant_id != actor.tenant_id:
            raise ValueError(f"DatasetInstance {dataset_id} not found")

        resource = await session.get(Resource, dataset_id)
        if not resource:
            raise ValueError(f"Dataset resource {dataset_id} not found")

        # 2. Check lineage freshness
        freshness_report = await self._lineage_resolver.check_upstream_freshness(
            session, dataset_id, self._freshness_checker
        )

        upstream_warning = None
        if not freshness_report.all_ready:
            if not force:
                raise UpstreamNotReadyError(
                    f"{len(freshness_report.blocking_resources)} upstream dependencies "
                    "are not ready. Use force=True to override.",
                    freshness_report.blocking_resources,
                )
            elif warn_on_stale:
                upstream_warning = self._format_upstream_warning(freshness_report)
                logger.warning(
                    f"Force-running pipeline for {dataset_id} with stale upstreams: "
                    f"{freshness_report.blocking_resources}"
                )

        # 3. Capture input versions for lineage
        input_versions = await self._capture_input_versions(
            session, dataset_id, freshness_report
        )

        # 4. Create PipelineRun resource
        run_id = uuid4()
        run_resource = Resource(
            id=run_id,
            tenant_id=actor.tenant_id,
            type="PipelineRun",
            parent_id=dataset_id,
            name=f"Pipeline run for {resource.name}",
            owner_principal_id=actor.id,
            status="active",
        )
        session.add(run_resource)

        # 5. Create PipelineRun extension
        pipeline_run = PipelineRun(
            resource_id=run_id,
            tenant_id=actor.tenant_id,
            dataset_instance_id=dataset_id,
            mode=mode,
            status="queued",
            input_versions_json=input_versions,
        )
        session.add(pipeline_run)
        await session.flush()

        # 6. Validate via GuardrailsEngine (if configured)
        if self._guardrails_engine:
            await self._validate_at_gate(
                session=session,
                actor=actor,
                resource_id=dataset_id,
                run_id=run_id,
                target_snapshot={
                    "mode": mode,
                    "input_versions": input_versions,
                    "force": force,
                },
            )

        # 7. Mark run start in status store
        await self._status_store.mark_run_start(dataset_id)

        # 8. Submit to orchestrator (via deployment or direct)
        submit_result = await self._submit_to_orchestrator(
            session=session,
            actor=actor,
            dataset=dataset,
            run_id=run_id,
            mode=mode,
        )

        # 9. Update PipelineRun with orchestrator info
        pipeline_run.orchestrator_kind = submit_result.orchestrator_kind
        pipeline_run.orchestrator_run_id = submit_result.orchestrator_run_id
        pipeline_run.orchestrator_meta_json = submit_result.orchestrator_meta
        pipeline_run.status = "running"
        pipeline_run.started_at = datetime.now(UTC)

        # 10. Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=run_id,
            resource_type="PipelineRun",
            action="pipeline.run_started",
            payload={
                "dataset_id": str(dataset_id),
                "mode": mode,
                "orchestrator_run_id": submit_result.orchestrator_run_id,
                "input_versions": input_versions,
                "forced": force,
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.flush()

        result = {
            "id": str(run_id),
            "dataset_id": str(dataset_id),
            "orchestrator_run_id": submit_result.orchestrator_run_id,
            "orchestrator_kind": submit_result.orchestrator_kind,
            "mode": mode,
            "status": "running",
            "started_at": pipeline_run.started_at.isoformat(),
        }

        if upstream_warning:
            result["upstream_warning"] = upstream_warning

        return result

    async def poll_and_sync(
        self,
        session: "AsyncSession",
        run_id: UUID | str,
    ) -> dict[str, Any]:
        """Poll orchestrator and sync status to PipelineRun.

        Args:
            session: Database session
            run_id: PipelineRun resource ID (UUID or string)

        Returns:
            Updated run information
        """
        # Convert string to UUID if needed
        if isinstance(run_id, str):
            run_id = UUID(run_id)

        # Load PipelineRun
        pipeline_run = await session.get(PipelineRun, run_id)
        if not pipeline_run:
            raise ValueError(f"PipelineRun {run_id} not found")

        resource = await session.get(Resource, run_id)

        # Skip if already in terminal state
        if pipeline_run.status in ("completed", "failed", "cancelled"):
            return self._run_to_dict(pipeline_run, resource)

        # Get orchestrator run ID
        if not pipeline_run.orchestrator_run_id:
            raise ValueError(f"PipelineRun {run_id} has no orchestrator_run_id")

        # Poll orchestrator
        status = await self._orchestrator.get_status(pipeline_run.orchestrator_run_id)

        # Update if status changed
        if status.status != pipeline_run.status:
            old_status = pipeline_run.status
            pipeline_run.status = status.status
            pipeline_run.finished_at = status.finished_at
            pipeline_run.error_summary = status.error_message

            # Extract metrics if available
            if status.metrics:
                pipeline_run.rows_processed = status.metrics.get("rows_processed")
                pipeline_run.start_data_date = status.metrics.get("start_data_date")
                pipeline_run.end_data_date = status.metrics.get("end_data_date")
                pipeline_run.extract_duration_ms = status.metrics.get(
                    "extract_duration_ms"
                )
                pipeline_run.transform_duration_ms = status.metrics.get(
                    "transform_duration_ms"
                )
                pipeline_run.load_duration_ms = status.metrics.get("load_duration_ms")

            await session.flush()

            # Handle completion
            if status.status == "completed":
                await self._on_run_completed(session, pipeline_run, status.metrics)
            elif status.status == "failed":
                await self._on_run_failed(session, pipeline_run)

            logger.info(
                f"PipelineRun {run_id} status changed: {old_status} -> {status.status}"
            )

        return self._run_to_dict(pipeline_run, resource)

    async def cancel_run(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        run_id: UUID,
    ) -> dict[str, Any]:
        """Cancel a running pipeline.

        Args:
            session: Database session
            actor: Actor context for RBAC
            run_id: PipelineRun resource ID

        Returns:
            Updated run information
        """
        pipeline_run = await session.get(PipelineRun, run_id)
        if not pipeline_run or pipeline_run.tenant_id != actor.tenant_id:
            raise ValueError(f"PipelineRun {run_id} not found")

        if not pipeline_run.orchestrator_run_id:
            raise ValueError(f"PipelineRun {run_id} has no orchestrator_run_id")

        # Cancel in orchestrator
        success = await self._orchestrator.cancel_run(pipeline_run.orchestrator_run_id)

        if success:
            pipeline_run.status = "cancelled"
            pipeline_run.finished_at = datetime.now(UTC)
            await session.flush()

            # Update status store
            await self._status_store.mark_run_error(
                pipeline_run.dataset_instance_id, "Cancelled by user"
            )

            # Emit activity
            envelope = ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=run_id,
                resource_type="PipelineRun",
                action="pipeline.run_cancelled",
                payload={
                    "dataset_id": str(pipeline_run.dataset_instance_id),
                    "orchestrator_run_id": pipeline_run.orchestrator_run_id,
                },
            )
            await record_activity_with_outbox(session, envelope)
            await session.flush()

        resource = await session.get(Resource, run_id)
        return self._run_to_dict(pipeline_run, resource)

    async def get_logs(
        self,
        session: "AsyncSession",
        run_id: UUID,
    ) -> str:
        """Get execution logs for a pipeline run.

        Args:
            session: Database session
            run_id: PipelineRun resource ID

        Returns:
            Log output as string
        """
        pipeline_run = await session.get(PipelineRun, run_id)
        if not pipeline_run:
            raise ValueError(f"PipelineRun {run_id} not found")

        if not pipeline_run.orchestrator_run_id:
            return "No orchestrator run ID"

        return await self._orchestrator.get_logs(pipeline_run.orchestrator_run_id)

    async def list_runs(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        *,
        dataset_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List pipeline runs with optional filters.

        Args:
            session: Database session
            actor: Actor context
            dataset_id: Filter by dataset
            status: Filter by status
            limit: Maximum results

        Returns:
            List of pipeline run info
        """
        from sqlalchemy import select

        stmt = (
            select(Resource, PipelineRun)
            .join(PipelineRun, Resource.id == PipelineRun.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "PipelineRun",
            )
        )

        if dataset_id:
            stmt = stmt.where(PipelineRun.dataset_instance_id == dataset_id)

        if status:
            stmt = stmt.where(PipelineRun.status == status)

        stmt = stmt.order_by(PipelineRun.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [self._run_to_dict(run, resource) for resource, run in rows]

    async def _submit_to_orchestrator(
        self,
        session: "AsyncSession",
        actor: "ActorContext",
        dataset: DatasetInstance,
        run_id: UUID,
        mode: str,
    ):
        """Submit run to orchestrator, preferring deployment trigger."""
        # Prefer deployment trigger if available
        if dataset.prefect_deployment_id:
            return await self._orchestrator.trigger_deployment(
                deployment_id=dataset.prefect_deployment_id,
                run_id=run_id,
                parameters={"mode": mode},
                tags={
                    "tenant_id": str(actor.tenant_id),
                    "actor_id": str(actor.id),
                    "dataset_id": str(dataset.resource_id),
                },
            )

        # Fall back to direct submission
        from libs.orchestration import build_graph

        graph = await build_graph(
            session=session,
            root_id=dataset.resource_id,
            tenant_id=actor.tenant_id,
            include_status=True,
        )

        return await self._orchestrator.submit_run(
            run_id=run_id,
            flow_definition=graph.to_dict(),
            config={"mode": mode},
            tags={
                "tenant_id": str(actor.tenant_id),
                "actor_id": str(actor.id),
                "run_type": "pipeline",
                "dataset_id": str(dataset.resource_id),
            },
        )

    async def _on_run_completed(
        self,
        session: "AsyncSession",
        pipeline_run: PipelineRun,
        metrics: Optional[dict[str, Any]],
    ) -> None:
        """Handle successful run completion."""
        # Update DatasetInstance freshness
        dataset = await session.get(DatasetInstance, pipeline_run.dataset_instance_id)
        if dataset:
            dataset.freshness_status = "fresh"
            dataset.last_refresh_at = datetime.now(UTC)
            dataset.row_count = pipeline_run.rows_processed
            dataset.last_data_date = pipeline_run.end_data_date

        # Update status store
        await self._status_store.mark_run_success(
            dataset_id=pipeline_run.dataset_instance_id,
            last_data_date=pipeline_run.end_data_date,
            rows_processed=pipeline_run.rows_processed,
        )

        # Load resource to get owner for activity/trigger
        run_resource = await session.get(Resource, pipeline_run.resource_id)
        owner_id = (
            run_resource.owner_principal_id if run_resource else pipeline_run.tenant_id
        )

        # Phase 2.8.3: Notify downstream dependents via observer pattern
        # This updates the downstream's upstream_status to mark this upstream as "ready"
        ready_ids = await self._lineage_observer.on_upstream_completed(
            session,
            upstream_id=pipeline_run.dataset_instance_id,
            run_id=pipeline_run.resource_id,
        )
        if ready_ids:
            logger.info(
                f"Notified downstreams: {len(ready_ids)} are now fully ready to run"
            )

        # Publish real-time notifications to Centrifugo for UI updates
        for downstream_id in ready_ids:
            # Notify UI
            await self._centrifugo_notifier.notify_upstream_ready(
                downstream_id=downstream_id,
                upstream_id=pipeline_run.dataset_instance_id,
                all_ready=True,
            )

            # Auto-trigger logic
            # Check if downstream should be auto-triggered
            downstream = await session.get(DatasetInstance, downstream_id)
            if downstream and downstream.auto_trigger:
                logger.info(f"Auto-triggering downstream dataset {downstream_id}")

                # Construct system actor for automated execution
                system_actor = ActorContext(
                    id=owner_id,  # Inherit owner for now to simplify RBAC
                    tenant_id=pipeline_run.tenant_id,
                    kind="system_automation",
                    traits={"trigger": "auto_lineage"},
                )

                try:
                    await self.submit_run(
                        session=session,
                        actor=system_actor,
                        dataset_id=downstream_id,
                        mode="incremental",
                        force=True,  # Skip freshness check - already verified by on_upstream_completed
                        warn_on_stale=False,  # Don't warn - we know upstreams are ready
                    )
                except Exception as e:
                    logger.error(f"Failed to auto-trigger {downstream_id}: {e}")

        # Also propagate staleness to invalidate downstream caches
        affected = await self._lineage_resolver.propagate_staleness(
            session, pipeline_run.dataset_instance_id
        )
        if affected:
            logger.info(f"Propagated staleness to {len(affected)} downstream resources")

        # Emit completion activity for real-time updates
        envelope = ActivityEnvelope(
            tenant_id=pipeline_run.tenant_id,
            actor_principal_id=owner_id,  # Use owner or fallback
            resource_id=pipeline_run.resource_id,
            resource_type="PipelineRun",
            action="pipeline.run_completed",
            payload={
                "dataset_id": str(pipeline_run.dataset_instance_id),
                "rows_processed": pipeline_run.rows_processed,
                "start_data_date": str(pipeline_run.start_data_date)
                if pipeline_run.start_data_date
                else None,
                "end_data_date": str(pipeline_run.end_data_date)
                if pipeline_run.end_data_date
                else None,
                "affected_downstream": len(affected),
                "ready_downstream_ids": [str(uid) for uid in ready_ids],
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.flush()

    async def _on_run_failed(
        self,
        session: "AsyncSession",
        pipeline_run: PipelineRun,
    ) -> None:
        """Handle run failure."""
        # Update DatasetInstance freshness
        dataset = await session.get(DatasetInstance, pipeline_run.dataset_instance_id)
        if dataset:
            dataset.freshness_status = "stale"

        # Update status store with error
        await self._status_store.mark_run_error(
            dataset_id=pipeline_run.dataset_instance_id,
            error_message=pipeline_run.error_summary or "Unknown error",
        )

        # Phase 2.8.3: Notify downstream dependents about failure
        affected_ids = await self._lineage_observer.on_upstream_failed(
            session,
            upstream_id=pipeline_run.dataset_instance_id,
            run_id=pipeline_run.resource_id,
            error=pipeline_run.error_summary,
        )
        if affected_ids:
            logger.warning(
                f"Notified {len(affected_ids)} downstreams about upstream failure"
            )

        # Publish real-time failure notifications to Centrifugo for UI updates
        for downstream_id in affected_ids:
            await self._centrifugo_notifier.notify_upstream_failed(
                downstream_id=downstream_id,
                upstream_id=pipeline_run.dataset_instance_id,
                error=pipeline_run.error_summary,
            )

        # Emit failure activity for real-time updates
        envelope = ActivityEnvelope(
            tenant_id=pipeline_run.tenant_id,
            actor_principal_id=None,  # System event
            resource_id=pipeline_run.resource_id,
            resource_type="PipelineRun",
            action="pipeline.run_failed",
            payload={
                "dataset_id": str(pipeline_run.dataset_instance_id),
                "error_summary": pipeline_run.error_summary,
                "affected_downstream_ids": [str(uid) for uid in affected_ids],
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.flush()

    async def _capture_input_versions(
        self,
        session: "AsyncSession",
        dataset_id: UUID,
        freshness_report: LineageFreshnessReport,
    ) -> dict[str, Any]:
        """Capture versions of upstream datasets for lineage tracking."""
        input_versions = {}

        for upstream_id in freshness_report.status_map.keys():
            upstream_status = await self._status_store.get_status(upstream_id)
            if upstream_status:
                input_versions[str(upstream_id)] = {
                    "last_data_date": (
                        str(upstream_status.last_data_date)
                        if upstream_status.last_data_date
                        else None
                    ),
                    "last_pipeline_run": (
                        upstream_status.last_pipeline_run.isoformat()
                        if upstream_status.last_pipeline_run
                        else None
                    ),
                    "status": str(
                        freshness_report.status_map.get(upstream_id, "unknown")
                    ),
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
            extra={"run_type": "PipelineRun"},
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

    def _format_upstream_warning(self, freshness_report: LineageFreshnessReport) -> str:
        """Format a human-readable warning about stale upstreams."""
        stale_by_status: dict[DatasetStatus, list[str]] = {}
        for uid in freshness_report.blocking_resources:
            status = freshness_report.status_map.get(uid, DatasetStatus.STALE)
            if status not in stale_by_status:
                stale_by_status[status] = []
            stale_by_status[status].append(str(uid))

        parts = []
        for status, uids in stale_by_status.items():
            parts.append(f"{len(uids)} {status.value}: {', '.join(uids[:3])}")
            if len(uids) > 3:
                parts[-1] += f" (+{len(uids) - 3} more)"

        return f"Running with stale upstreams: {'; '.join(parts)}"

    def _run_to_dict(
        self, pipeline_run: PipelineRun, resource: Optional[Resource]
    ) -> dict[str, Any]:
        """Convert PipelineRun to dict."""
        return {
            "id": str(pipeline_run.resource_id),
            "type": "PipelineRun",
            "name": resource.name if resource else None,
            "dataset_id": str(pipeline_run.dataset_instance_id),
            "mode": pipeline_run.mode,
            "status": pipeline_run.status,
            "orchestrator_kind": pipeline_run.orchestrator_kind,
            "orchestrator_run_id": pipeline_run.orchestrator_run_id,
            "rows_processed": pipeline_run.rows_processed,
            "start_data_date": (
                str(pipeline_run.start_data_date)
                if pipeline_run.start_data_date
                else None
            ),
            "end_data_date": (
                str(pipeline_run.end_data_date) if pipeline_run.end_data_date else None
            ),
            "error_summary": pipeline_run.error_summary,
            "started_at": (
                pipeline_run.started_at.isoformat() if pipeline_run.started_at else None
            ),
            "finished_at": (
                pipeline_run.finished_at.isoformat()
                if pipeline_run.finished_at
                else None
            ),
            "created_at": pipeline_run.created_at.isoformat(),
        }
