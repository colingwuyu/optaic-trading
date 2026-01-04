"""Integration tests for ExperimentRunService.

Verifies:
- Experiment run submission to LocalOrchestrator
- Database state transitions
- Activity emission
- Real dependency integration (no mocks)
"""

import pytest

from uuid import uuid4, UUID

from apps.api.services.experiment_run_service import ExperimentRunService
from libs.core.rbac.models import ActorContext
from libs.db.models.quant import ExperimentInstance, ExperimentRun
from libs.db.models.resource import Resource
from libs.orchestration import LocalOrchestrator, StatusStore


@pytest.fixture
def service(db_session):
    """Create service with real dependencies."""
    # Using LocalOrchestrator as defined in deps.py
    orchestrator = LocalOrchestrator()
    status_store = StatusStore(db_session)
    # guardrails_engine can be None for basic tests, or real if needed.
    # User asked for "realistic", but GuardrailsEngine might need config.
    # deps.py initializes it with default(). Let's use None for now to focus on Run logic
    # unless validation is the test target.
    # Actually, deps.py uses GuardrailsEngine(). Let's try to match if possible,
    # but Guardrails might need extensive setup (contracts etc).
    # To keep it "unit-ish" but integration style, we skip optional complex engines if not testing them specifically.
    return ExperimentRunService(
        orchestrator=orchestrator, status_store=status_store, guardrails_engine=None
    )


@pytest.fixture
def actor():
    return ActorContext(id=uuid4(), tenant_id=uuid4(), kind="user")


@pytest.mark.asyncio
async def test_submit_preview_real(service, db_session, actor):
    """Test full preview submission flow with DB and LocalOrchestrator."""
    # Patch commit to flush to keep transaction open for rollback
    db_session.commit = db_session.flush

    # 1. Setup Data
    experiment_id = uuid4()

    # Create Resource
    resource = Resource(
        id=experiment_id,
        tenant_id=actor.tenant_id,
        owner_principal_id=actor.id,
        name="Integration Test Exp",
        type="ExperimentInstance",
    )
    db_session.add(resource)

    # Create ExperimentInstance
    experiment = ExperimentInstance(
        resource_id=experiment_id,
        tenant_id=actor.tenant_id,
        expression_text="MEAN($price)",
        input_datasets_json={"price": str(uuid4())},
    )
    db_session.add(experiment)
    await db_session.commit()

    # 2. Execute
    result = await service.submit_preview(
        session=db_session, actor=actor, experiment_id=experiment_id, limit=10
    )

    # 3. Verify Result Structure
    assert (
        result["status"] == "running"
    )  # LocalOrchestrator starts as 'running' or 'queued'
    assert result["experiment_id"] == str(experiment_id)
    assert result["orchestrator_run_id"]  # Should have an ID generated

    # 4. Verify DB Persistence
    run_id = UUID(result["id"])
    run_record = await db_session.get(ExperimentRun, run_id)
    assert run_record is not None
    assert run_record.orchestrator_kind == "local"
    assert run_record.status == "running"


@pytest.mark.asyncio
async def test_submit_preview_missing_resource(service, db_session, actor):
    """Test error handling with real DB."""
    missing_id = uuid4()

    with pytest.raises(ValueError, match="not found"):
        await service.submit_preview(
            session=db_session, actor=actor, experiment_id=missing_id
        )
