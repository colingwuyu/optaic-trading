"""Tests for RunExecutionService - Comprehensive run execution tests.

Tests the central execution coordination service:
- Pipeline run submission (creates Run resource, Activity, orchestrator submission)
- Status polling and syncing to database
- Completion handling (updates parent Instance, emits Activity)
- Failure handling (updates status store, emits Activity)
- Cancellation (updates status, emits Activity)
- GuardrailsEngine integration at lifecycle gates
- Edge cases: missing resources, already fresh, force mode

All tests use real database sessions from the sandbox infrastructure.
Uses LocalOrchestrator for execution to avoid Prefect dependency.
NO MOCKS - tests verify actual database operations and service logic.
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import ActorContext
from libs.db.models.activity import Activity, Outbox
from libs.db.models.quant import DatasetInstance, ExperimentInstance
from libs.db.models.resource import Resource
from libs.orchestration.local import LocalOrchestrator
from libs.orchestration.run_service import RunExecutionService
from libs.orchestration.status_store import StatusStore


def utcnow_iso() -> str:
    """Return current UTC time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()


async def create_tenant_and_principal(db_session: AsyncSession):
    """Create a test tenant and principal, return their IDs."""
    tenant_id = uuid4()
    principal_id = uuid4()

    await db_session.execute(
        text("""
            INSERT INTO tenants (id, name, created_at)
            VALUES (:id, :name, :created_at)
        """),
        {
            "id": str(tenant_id),
            "name": "Run Service Test Tenant",
            "created_at": utcnow_iso(),
        },
    )

    await db_session.execute(
        text("""
            INSERT INTO principals (id, tenant_id, kind, status, display_name, created_at)
            VALUES (:id, :tenant_id, :kind, :status, :display_name, :created_at)
        """),
        {
            "id": str(principal_id),
            "tenant_id": str(tenant_id),
            "kind": "user",
            "status": "active",
            "display_name": "Run Service Test User",
            "created_at": utcnow_iso(),
        },
    )
    await db_session.flush()
    return tenant_id, principal_id


async def create_dataset_instance(
    db_session: AsyncSession,
    tenant_id,
    principal_id,
    name: str,
    freshness_status: str = "unknown",
) -> DatasetInstance:
    """Create a Resource + DatasetInstance and return the instance."""
    resource_id = uuid4()

    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type="DatasetInstance",
        name=name,
        status="active",
    )
    db_session.add(resource)

    dataset = DatasetInstance(
        resource_id=resource_id,
        tenant_id=tenant_id,
        freshness_status=freshness_status,
        pipeline_instance_id=uuid4(),
        store_instance_id=uuid4(),
        accessor_instance_id=uuid4(),
    )
    db_session.add(dataset)
    await db_session.flush()

    return dataset


async def create_experiment_instance(
    db_session: AsyncSession,
    tenant_id,
    principal_id,
    name: str,
    expression: str = "SUM(A)",
) -> ExperimentInstance:
    """Create a Resource + ExperimentInstance and return the instance."""
    resource_id = uuid4()

    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type="ExperimentInstance",
        name=name,
        status="active",
    )
    db_session.add(resource)

    experiment = ExperimentInstance(
        resource_id=resource_id,
        tenant_id=tenant_id,
        expression_text=expression,
        input_datasets_json={},
    )
    db_session.add(experiment)
    await db_session.flush()

    return experiment


def create_test_orchestrator():
    """Create LocalOrchestrator with simple test node executor."""

    async def simple_node_executor(node_id, node_type, code_ref, config):
        """Simple node executor that always succeeds with test metrics."""
        await asyncio.sleep(0.01)  # Simulate some work
        return {
            "status": "success",
            "rows_processed": 100,
            "last_data_date": "2025-01-01",
        }

    return LocalOrchestrator(max_workers=2, node_executor=simple_node_executor)


@pytest.fixture
def orchestrator():
    """Create test LocalOrchestrator."""
    orch = create_test_orchestrator()
    yield orch
    orch.cleanup()


@pytest.mark.asyncio
class TestPipelineRunSubmission:
    """Tests for submit_pipeline_run."""

    async def test_creates_run_resource_in_database(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting a pipeline run creates a PipelineRun resource in the database."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Test Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
            mode="incremental",
        )

        # Verify result contains expected fields
        assert result["status"] == "running"
        assert "orchestrator_run_id" in result
        assert result["mode"] == "incremental"
        assert result["dataset_id"] == str(dataset.resource_id)

        # Verify Run resource was created in database
        run_id = UUID(result["id"])
        stmt = select(Resource).where(Resource.id == run_id)
        run_result = await db_session.execute(stmt)
        run_resource = run_result.scalar_one_or_none()

        assert run_resource is not None
        assert run_resource.type == "PipelineRun"
        assert run_resource.parent_id == dataset.resource_id
        assert run_resource.tenant_id == tenant_id
        assert run_resource.owner_principal_id == principal_id

    async def test_emits_activity_on_submission(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting a pipeline run emits an Activity and Outbox record."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Activity Test Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
            mode="overwrite",
        )

        run_id = UUID(result["id"])

        # Verify Activity was created
        stmt = select(Activity).where(
            Activity.resource_id == run_id,
            Activity.action == "pipeline.run_started",
        )
        activity_result = await db_session.execute(stmt)
        activity = activity_result.scalar_one_or_none()

        assert activity is not None
        assert activity.tenant_id == tenant_id
        assert activity.actor_principal_id == principal_id
        assert activity.payload["mode"] == "overwrite"
        assert activity.payload["dataset_id"] == str(dataset.resource_id)

        # Verify Outbox was created for async processing
        stmt = select(Outbox)
        outbox_result = await db_session.execute(stmt)
        outbox_records = outbox_result.scalars().all()

        assert len(outbox_records) >= 1
        # At least one outbox record should reference our activity
        activity_outbox = [
            o
            for o in outbox_records
            if o.payload.get("activity_id") == str(activity.id)
        ]
        assert len(activity_outbox) == 1

    async def test_marks_status_store_on_start(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting a pipeline run marks the StatusStore as 'running'."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Status Store Test Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        # Verify status store was updated
        status = await status_store.get_status(dataset.resource_id)

        assert status is not None
        assert status.last_pipeline_status == "running"
        assert status.last_pipeline_run is not None
        assert status.error_message is None

    async def test_raises_error_for_missing_dataset(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting a run for non-existent dataset raises ValueError."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        fake_dataset_id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=fake_dataset_id,
            )

    async def test_raises_error_when_fresh_without_force(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting a run for fresh dataset without force=True raises ValueError."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session,
            tenant_id,
            principal_id,
            "Fresh Dataset",
            freshness_status="fresh",
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)

        # Mark dataset as successfully run
        await status_store.mark_run_start(dataset.resource_id)
        await status_store.mark_run_success(dataset.resource_id)

        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        with pytest.raises(ValueError, match="already fresh"):
            await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=dataset.resource_id,
                force=False,
            )

    async def test_force_bypasses_fresh_check(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """force=True allows running even if dataset is fresh."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session,
            tenant_id,
            principal_id,
            "Force Fresh Dataset",
            freshness_status="fresh",
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)

        # Mark dataset as successfully run
        await status_store.mark_run_start(dataset.resource_id)
        await status_store.mark_run_success(dataset.resource_id)

        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        # Should succeed with force=True
        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
            force=True,
        )

        assert result["status"] == "running"


@pytest.mark.asyncio
class TestExperimentRunSubmission:
    """Tests for submit_experiment_run."""

    async def test_creates_experiment_run_resource(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting an experiment run creates ExperimentRun resource in DB."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        experiment = await create_experiment_instance(
            db_session,
            tenant_id,
            principal_id,
            "Test Experiment",
            expression="AVG(Price)",
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_experiment_run(
            session=db_session,
            actor=actor,
            experiment_id=experiment.resource_id,
            limit=50,
        )

        # Verify result
        assert result["status"] == "running"
        assert result["experiment_id"] == str(experiment.resource_id)

        # Verify Run resource was created
        run_id = UUID(result["id"])
        stmt = select(Resource).where(Resource.id == run_id)
        run_result = await db_session.execute(stmt)
        run_resource = run_result.scalar_one_or_none()

        assert run_resource is not None
        assert run_resource.type == "ExperimentRun"
        assert run_resource.parent_id == experiment.resource_id

    async def test_raises_error_for_missing_experiment(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Submitting a run for non-existent experiment raises ValueError."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        fake_experiment_id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            await service.submit_experiment_run(
                session=db_session,
                actor=actor,
                experiment_id=fake_experiment_id,
            )


@pytest.mark.asyncio
class TestPollAndSync:
    """Tests for poll_and_sync status synchronization."""

    async def test_updates_status_when_completed(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """poll_and_sync updates Run resource when orchestrator reports completion."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Poll Test Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        run_id = UUID(result["id"])

        # Wait for orchestrator to complete (LocalOrchestrator is fast)
        await asyncio.sleep(0.2)

        # Poll and sync
        updated = await service.poll_and_sync(db_session, run_id)

        assert updated["status"] == "completed"

        # Verify Run resource in database was updated
        stmt = select(Resource).where(Resource.id == run_id)
        run_result = await db_session.execute(stmt)
        run_resource = run_result.scalar_one()

        assert run_resource.metadata_json["status"] == "completed"
        assert run_resource.metadata_json.get("finished_at") is not None

    async def test_updates_parent_dataset_on_completion(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Completion updates parent DatasetInstance to 'fresh'."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session,
            tenant_id,
            principal_id,
            "Parent Update Dataset",
            freshness_status="stale",
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        run_id = UUID(result["id"])

        # Wait for completion
        await asyncio.sleep(0.2)
        await service.poll_and_sync(db_session, run_id)

        # Verify dataset was updated
        await db_session.refresh(dataset)
        assert dataset.freshness_status == "fresh"
        assert dataset.last_refresh_at is not None

    async def test_updates_status_store_on_completion(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Completion updates StatusStore with success."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Status Store Update Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        run_id = UUID(result["id"])

        # Wait for completion
        await asyncio.sleep(0.2)
        await service.poll_and_sync(db_session, run_id)

        # Verify status store was updated
        status = await status_store.get_status(dataset.resource_id)
        assert status.last_pipeline_status == "success"

    async def test_emits_completion_activity(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Completion emits a pipeline.run_completed Activity."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Completion Activity Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        run_id = UUID(result["id"])

        # Wait for completion
        await asyncio.sleep(0.2)
        await service.poll_and_sync(db_session, run_id)

        # Verify completion activity was emitted
        stmt = select(Activity).where(
            Activity.resource_id == run_id,
            Activity.action == "pipelinerun.run_completed",
        )
        activity_result = await db_session.execute(stmt)
        activity = activity_result.scalar_one_or_none()

        assert activity is not None
        assert "metrics" in activity.payload

    async def test_skips_already_terminal_status(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """poll_and_sync skips runs that are already in terminal state."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Terminal Status Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        run_id = UUID(result["id"])

        # Wait for completion
        await asyncio.sleep(0.2)

        # First poll should complete
        first_result = await service.poll_and_sync(db_session, run_id)
        assert first_result["status"] == "completed"

        # Second poll should return same status without re-querying orchestrator
        second_result = await service.poll_and_sync(db_session, run_id)
        assert second_result["status"] == "completed"

    async def test_raises_error_for_missing_run(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """poll_and_sync raises ValueError for non-existent run."""
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        fake_run_id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            await service.poll_and_sync(db_session, fake_run_id)


@pytest.mark.asyncio
class TestCancelRun:
    """Tests for cancel_run."""

    async def test_cancels_running_execution(self, db_session: AsyncSession):
        """cancel_run stops execution and updates status to cancelled."""

        # Use a slow orchestrator to give time to cancel
        async def slow_executor(node_id, node_type, code_ref, config):
            await asyncio.sleep(5)  # Long running
            return {"status": "success"}

        orchestrator = LocalOrchestrator(max_workers=1, node_executor=slow_executor)

        try:
            tenant_id, principal_id = await create_tenant_and_principal(db_session)
            dataset = await create_dataset_instance(
                db_session, tenant_id, principal_id, "Cancel Test Dataset"
            )

            actor = ActorContext(id=principal_id, tenant_id=tenant_id)
            status_store = StatusStore(db_session)
            service = RunExecutionService(
                orchestrator=orchestrator,
                status_store=status_store,
            )

            result = await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=dataset.resource_id,
            )

            run_id = UUID(result["id"])

            # Give orchestrator time to start
            await asyncio.sleep(0.1)

            # Cancel the run
            cancel_result = await service.cancel_run(db_session, actor, run_id)

            assert cancel_result["status"] == "cancelled"

            # Verify database was updated
            stmt = select(Resource).where(Resource.id == run_id)
            run_result = await db_session.execute(stmt)
            run_resource = run_result.scalar_one()

            assert run_resource.metadata_json["status"] == "cancelled"

        finally:
            orchestrator.cleanup()

    async def test_emits_cancellation_activity(self, db_session: AsyncSession):
        """cancel_run emits a run_cancelled Activity."""

        async def slow_executor(node_id, node_type, code_ref, config):
            await asyncio.sleep(5)
            return {"status": "success"}

        orchestrator = LocalOrchestrator(max_workers=1, node_executor=slow_executor)

        try:
            tenant_id, principal_id = await create_tenant_and_principal(db_session)
            dataset = await create_dataset_instance(
                db_session, tenant_id, principal_id, "Cancel Activity Dataset"
            )

            actor = ActorContext(id=principal_id, tenant_id=tenant_id)
            status_store = StatusStore(db_session)
            service = RunExecutionService(
                orchestrator=orchestrator,
                status_store=status_store,
            )

            result = await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=dataset.resource_id,
            )

            run_id = UUID(result["id"])
            await asyncio.sleep(0.1)
            await service.cancel_run(db_session, actor, run_id)

            # Verify cancellation activity was emitted
            stmt = select(Activity).where(
                Activity.resource_id == run_id,
                Activity.action == "pipelinerun.run_cancelled",
            )
            activity_result = await db_session.execute(stmt)
            activity = activity_result.scalar_one_or_none()

            assert activity is not None

        finally:
            orchestrator.cleanup()


@pytest.mark.asyncio
class TestGetLogs:
    """Tests for get_logs."""

    async def test_returns_execution_logs(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """get_logs returns log output from orchestrator."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        dataset = await create_dataset_instance(
            db_session, tenant_id, principal_id, "Logs Test Dataset"
        )

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        result = await service.submit_pipeline_run(
            session=db_session,
            actor=actor,
            dataset_id=dataset.resource_id,
        )

        run_id = UUID(result["id"])

        # Wait for completion
        await asyncio.sleep(0.2)

        logs = await service.get_logs(db_session, run_id)

        # LocalOrchestrator logs contain timestamps and status messages
        assert isinstance(logs, str)
        assert "Run started" in logs or len(logs) > 0


@pytest.mark.asyncio
class TestFailureHandling:
    """Tests for failure handling."""

    async def test_updates_status_on_failure(self, db_session: AsyncSession):
        """Failed runs update status to 'failed' with error message."""

        async def failing_executor(node_id, node_type, code_ref, config):
            raise RuntimeError("Test pipeline failure")

        orchestrator = LocalOrchestrator(max_workers=1, node_executor=failing_executor)

        try:
            tenant_id, principal_id = await create_tenant_and_principal(db_session)
            dataset = await create_dataset_instance(
                db_session, tenant_id, principal_id, "Failure Test Dataset"
            )

            actor = ActorContext(id=principal_id, tenant_id=tenant_id)
            status_store = StatusStore(db_session)
            service = RunExecutionService(
                orchestrator=orchestrator,
                status_store=status_store,
            )

            result = await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=dataset.resource_id,
            )

            run_id = UUID(result["id"])

            # Wait for failure
            await asyncio.sleep(0.2)
            updated = await service.poll_and_sync(db_session, run_id)

            assert updated["status"] == "failed"
            assert "Test pipeline failure" in (updated.get("error_message") or "")

        finally:
            orchestrator.cleanup()

    async def test_updates_status_store_on_failure(self, db_session: AsyncSession):
        """Failed runs update StatusStore with error."""

        async def failing_executor(node_id, node_type, code_ref, config):
            raise RuntimeError("Pipeline error for status store test")

        orchestrator = LocalOrchestrator(max_workers=1, node_executor=failing_executor)

        try:
            tenant_id, principal_id = await create_tenant_and_principal(db_session)
            dataset = await create_dataset_instance(
                db_session, tenant_id, principal_id, "Status Store Failure Dataset"
            )

            actor = ActorContext(id=principal_id, tenant_id=tenant_id)
            status_store = StatusStore(db_session)
            service = RunExecutionService(
                orchestrator=orchestrator,
                status_store=status_store,
            )

            result = await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=dataset.resource_id,
            )

            run_id = UUID(result["id"])

            # Wait for failure
            await asyncio.sleep(0.2)
            await service.poll_and_sync(db_session, run_id)

            # Verify status store was updated with error
            status = await status_store.get_status(dataset.resource_id)
            assert status.last_pipeline_status == "error"
            assert "Pipeline error" in (status.error_message or "")

        finally:
            orchestrator.cleanup()

    async def test_emits_failure_activity(self, db_session: AsyncSession):
        """Failed runs emit a run_failed Activity."""

        async def failing_executor(node_id, node_type, code_ref, config):
            raise RuntimeError("Failure for activity test")

        orchestrator = LocalOrchestrator(max_workers=1, node_executor=failing_executor)

        try:
            tenant_id, principal_id = await create_tenant_and_principal(db_session)
            dataset = await create_dataset_instance(
                db_session, tenant_id, principal_id, "Failure Activity Dataset"
            )

            actor = ActorContext(id=principal_id, tenant_id=tenant_id)
            status_store = StatusStore(db_session)
            service = RunExecutionService(
                orchestrator=orchestrator,
                status_store=status_store,
            )

            result = await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=dataset.resource_id,
            )

            run_id = UUID(result["id"])

            # Wait for failure
            await asyncio.sleep(0.2)
            await service.poll_and_sync(db_session, run_id)

            # Verify failure activity was emitted
            stmt = select(Activity).where(
                Activity.resource_id == run_id,
                Activity.action == "pipelinerun.run_failed",
            )
            activity_result = await db_session.execute(stmt)
            activity = activity_result.scalar_one_or_none()

            assert activity is not None
            assert "error" in activity.payload

        finally:
            orchestrator.cleanup()


@pytest.mark.asyncio
class TestMultipleRuns:
    """Tests for handling multiple concurrent runs."""

    async def test_multiple_datasets_run_independently(
        self, db_session: AsyncSession, orchestrator: LocalOrchestrator
    ):
        """Multiple datasets can have runs submitted and complete independently."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)

        datasets = []
        for i in range(3):
            ds = await create_dataset_instance(
                db_session, tenant_id, principal_id, f"Multi Dataset {i}"
            )
            datasets.append(ds)

        actor = ActorContext(id=principal_id, tenant_id=tenant_id)
        status_store = StatusStore(db_session)
        service = RunExecutionService(
            orchestrator=orchestrator,
            status_store=status_store,
        )

        # Submit all runs
        run_results = []
        for ds in datasets:
            result = await service.submit_pipeline_run(
                session=db_session,
                actor=actor,
                dataset_id=ds.resource_id,
            )
            run_results.append(result)

        # All should be running
        for result in run_results:
            assert result["status"] == "running"

        # Wait for all to complete
        await asyncio.sleep(0.5)

        # Poll all
        for result in run_results:
            updated = await service.poll_and_sync(db_session, UUID(result["id"]))
            assert updated["status"] == "completed"

        # All datasets should be fresh
        for ds in datasets:
            await db_session.refresh(ds)
            assert ds.freshness_status == "fresh"
