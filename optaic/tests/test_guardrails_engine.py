"""Unit tests for GuardrailsEngine.

Tests use real database sessions from sandbox infrastructure (NO MOCKS policy).
All database operations are performed via actual SQL, not mock objects.
"""

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from optaic.guardrails.contracts.base import (
    ContractBundle,
    ContractInstance,
    ContractRef,
)
from optaic.guardrails.contracts.registry import ContractRegistry
from optaic.guardrails.runtime.context import GuardrailsContext
from optaic.guardrails.runtime.engine import GuardrailsBlocked, GuardrailsEngine
from optaic.guardrails.storage import ContractBundleStore
from optaic.guardrails.validators.base import ContractValidator, ValidationIssue


class TestValidator(ContractValidator):
    """A test validator that returns issues based on the target_snapshot."""

    @property
    def name(self) -> str:
        return "test_fail"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        """Return issues if 'fail' key is True in target_snapshot."""
        if isinstance(target_snapshot, dict) and target_snapshot.get("fail"):
            return [
                ValidationIssue(
                    code="TEST_FAIL",
                    severity="error",
                    message="Test validation failed",
                    path=".",
                )
            ]
        return []


class PassingValidator(ContractValidator):
    """A test validator that always passes."""

    @property
    def name(self) -> str:
        return "test_pass"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        """Always return empty list (pass)."""
        return []


@pytest.fixture
def registry() -> ContractRegistry:
    """Create a registry with test validators."""
    reg = ContractRegistry()
    # Register contract kinds with their schemas
    reg.register_contract_kind(
        kind="test",
        version="1",
        json_schema={"type": "object"},  # Simple schema
        default_validator="test_fail",
    )
    reg.register_contract_kind(
        kind="test_pass",
        version="1",
        json_schema={"type": "object"},
        default_validator="test_pass",
    )
    # Register validators
    reg.register_validator("test_fail", TestValidator)
    reg.register_validator("test_pass", PassingValidator)
    return reg


@pytest.fixture
def engine(registry: ContractRegistry) -> GuardrailsEngine:
    """Create a guardrails engine with test registry."""
    return GuardrailsEngine(registry=registry)


@pytest.fixture
def context() -> GuardrailsContext:
    """Create a test context for official subspace (enforces 'block')."""
    return GuardrailsContext(
        tenant_id=uuid4(),
        actor_principal_id=uuid4(),
        action="update",
        space_kind="team",
        subspace_kind="official",
    )


@pytest.fixture
def staging_context() -> GuardrailsContext:
    """Create a test context for staging subspace (enforces 'warn')."""
    return GuardrailsContext(
        tenant_id=uuid4(),
        actor_principal_id=uuid4(),
        action="update",
        space_kind="team",
        subspace_kind="staging",
    )


async def setup_resource_and_tenant(
    db: AsyncSession, tenant_id: str, principal_id: str
) -> str:
    """Create tenant, principal, and resource for testing.

    Returns:
        The resource_id of the created resource.
    """
    resource_id = str(uuid4())

    # Create tenant if not exists (use INSERT OR IGNORE for SQLite)
    await db.execute(
        text("""
            INSERT OR IGNORE INTO tenants (id, name)
            VALUES (:id, :name)
        """),
        {"id": tenant_id, "name": f"Tenant-{tenant_id[:8]}"},
    )

    # Create principal if not exists
    await db.execute(
        text("""
            INSERT OR IGNORE INTO principals (id, tenant_id, kind, status, display_name)
            VALUES (:id, :tenant_id, :kind, :status, :display_name)
        """),
        {
            "id": principal_id,
            "tenant_id": tenant_id,
            "kind": "user",
            "status": "active",
            "display_name": f"User-{principal_id[:8]}",
        },
    )

    # Create resource
    await db.execute(
        text("""
            INSERT INTO resources (id, tenant_id, owner_principal_id, type, name, status, metadata, created_at, updated_at)
            VALUES (:id, :tenant_id, :owner_principal_id, :type, :name, :status, :metadata, datetime('now'), datetime('now'))
        """),
        {
            "id": resource_id,
            "tenant_id": tenant_id,
            "owner_principal_id": principal_id,
            "type": "Signal",
            "name": f"TestResource-{resource_id[:8]}",
            "status": "active",
            "metadata": "{}",
        },
    )

    await db.flush()
    return resource_id


@pytest.mark.asyncio
async def test_validate_no_bundle_returns_ok_report(
    db_session: AsyncSession, engine: GuardrailsEngine, context: GuardrailsContext
):
    """Test that if no bundle exists, we get a passing report."""
    # Setup: create resource without any contract bundle
    resource_id = await setup_resource_and_tenant(
        db_session, str(context.tenant_id), str(context.actor_principal_id)
    )
    target_id = str(uuid4())

    # Execute validation
    report = await engine.validate_at_gate(
        db=db_session,
        scope="resource",
        target_id=target_id,
        resource_id=resource_id,
        context=context,
        target_snapshot={"value": 0.5},  # Any snapshot
    )

    # Verify report
    assert report.ok is True
    assert report.enforced_as == "warn"  # Default when no contracts
    assert len(report.issues) == 0

    # Verify report was persisted
    result = await db_session.execute(
        text(
            "SELECT report_id, ok, enforced_as FROM validation_reports WHERE report_id = :id"
        ),
        {"id": report.report_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[1] == 1  # ok = True (SQLite uses 1/0)
    assert row[2] == "warn"


@pytest.mark.asyncio
async def test_validate_passing_bundle_returns_ok(
    db_session: AsyncSession, engine: GuardrailsEngine, context: GuardrailsContext
):
    """Test that a passing validation returns ok=True."""
    # Setup
    resource_id = await setup_resource_and_tenant(
        db_session, str(context.tenant_id), str(context.actor_principal_id)
    )
    target_id = str(uuid4())

    # Create a bundle with a passing contract
    bundle = ContractBundle(
        bundle_id=str(uuid4()),
        resource_id=resource_id,
        created_by=str(context.actor_principal_id),
        contracts=[
            ContractInstance(
                ref=ContractRef(
                    contract_kind="test_pass", contract_name="pass_test", version="1"
                ),
                config_json="{}",
                contract_hash="hash_pass",
                enforcement_hint="block",
            )
        ],
    )
    await ContractBundleStore.upsert_active_bundle(db_session, bundle)
    await db_session.flush()

    # Execute validation (with snapshot that doesn't trigger failure)
    report = await engine.validate_at_gate(
        db=db_session,
        scope="resource",
        target_id=target_id,
        resource_id=resource_id,
        context=context,
        target_snapshot={"value": 0.5},  # Doesn't have "fail" key
    )

    # Verify report
    assert report.ok is True
    assert len(report.issues) == 0


@pytest.mark.asyncio
async def test_validate_official_blocks_on_error(
    db_session: AsyncSession, engine: GuardrailsEngine, context: GuardrailsContext
):
    """Test that errors in 'official' subspace with 'block' hint raise GuardrailsBlocked."""
    # Setup
    resource_id = await setup_resource_and_tenant(
        db_session, str(context.tenant_id), str(context.actor_principal_id)
    )
    target_id = str(uuid4())

    # Create a bundle with failing contract
    bundle = ContractBundle(
        bundle_id=str(uuid4()),
        resource_id=resource_id,
        created_by=str(context.actor_principal_id),
        contracts=[
            ContractInstance(
                ref=ContractRef(
                    contract_kind="test", contract_name="fail_test", version="1"
                ),
                config_json="{}",
                contract_hash="hash_fail",
                enforcement_hint="block",  # Blocking enforcement
            )
        ],
    )
    await ContractBundleStore.upsert_active_bundle(db_session, bundle)
    await db_session.flush()

    # Execute validation (with failing snapshot)
    with pytest.raises(GuardrailsBlocked) as exc:
        await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=target_id,
            resource_id=resource_id,
            context=context,  # subspace_kind='official' -> blocks
            target_snapshot={"fail": True},  # Triggers failure
        )

    # Verify exception details
    assert "1 issues found" in str(exc.value)
    assert len(exc.value.issues) == 1
    assert exc.value.issues[0].code == "TEST_FAIL"


@pytest.mark.asyncio
async def test_validate_staging_warns_on_error(
    db_session: AsyncSession,
    engine: GuardrailsEngine,
    staging_context: GuardrailsContext,
):
    """Test that errors in 'staging' subspace DO NOT block even with 'block' hint."""
    # Setup
    resource_id = await setup_resource_and_tenant(
        db_session,
        str(staging_context.tenant_id),
        str(staging_context.actor_principal_id),
    )
    target_id = str(uuid4())

    # Create a bundle with failing contract (block hint)
    bundle = ContractBundle(
        bundle_id=str(uuid4()),
        resource_id=resource_id,
        created_by=str(staging_context.actor_principal_id),
        contracts=[
            ContractInstance(
                ref=ContractRef(
                    contract_kind="test", contract_name="fail_test", version="1"
                ),
                config_json="{}",
                contract_hash="hash_fail",
                enforcement_hint="block",  # Says block, but staging policy overrides
            )
        ],
    )
    await ContractBundleStore.upsert_active_bundle(db_session, bundle)
    await db_session.flush()

    # Execute validation - should NOT raise exception
    report = await engine.validate_at_gate(
        db=db_session,
        scope="resource",
        target_id=target_id,
        resource_id=resource_id,
        context=staging_context,  # subspace_kind='staging' -> warns only
        target_snapshot={"fail": True},  # Triggers failure
    )

    # Verify report
    assert report.ok is False  # Validation failed
    assert report.enforced_as == "warn"  # But policy says warn, not block
    assert len(report.issues) == 1


@pytest.mark.asyncio
async def test_bundle_replacement_uses_latest(
    db_session: AsyncSession, engine: GuardrailsEngine, context: GuardrailsContext
):
    """Test that upserting a new bundle replaces the previous one."""
    # Setup
    resource_id = await setup_resource_and_tenant(
        db_session, str(context.tenant_id), str(context.actor_principal_id)
    )
    target_id = str(uuid4())

    # Create first bundle with failing contract
    bundle1 = ContractBundle(
        bundle_id=str(uuid4()),
        resource_id=resource_id,
        created_by=str(context.actor_principal_id),
        contracts=[
            ContractInstance(
                ref=ContractRef(
                    contract_kind="test", contract_name="fail_test", version="1"
                ),
                config_json="{}",
                contract_hash="hash_fail",
                enforcement_hint="block",
            )
        ],
    )
    await ContractBundleStore.upsert_active_bundle(db_session, bundle1)
    await db_session.flush()

    # Replace with passing bundle
    bundle2 = ContractBundle(
        bundle_id=str(uuid4()),
        resource_id=resource_id,
        created_by=str(context.actor_principal_id),
        contracts=[
            ContractInstance(
                ref=ContractRef(
                    contract_kind="test_pass", contract_name="pass_test", version="1"
                ),
                config_json="{}",
                contract_hash="hash_pass",
                enforcement_hint="block",
            )
        ],
    )
    await ContractBundleStore.upsert_active_bundle(db_session, bundle2)
    await db_session.flush()

    # Validation should now pass (using the new bundle)
    report = await engine.validate_at_gate(
        db=db_session,
        scope="resource",
        target_id=target_id,
        resource_id=resource_id,
        context=context,
        target_snapshot={"fail": True},  # Would fail with old bundle
    )

    assert report.ok is True  # New bundle uses passing validator

    # Verify only one active bundle exists
    result = await db_session.execute(
        text("""
            SELECT COUNT(*) FROM resource_contract_bundles
            WHERE resource_id = :id AND is_active = 1
        """),
        {"id": resource_id},
    )
    count = result.scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_report_persisted_with_correlation_id(
    db_session: AsyncSession, engine: GuardrailsEngine
):
    """Test that correlation_id is properly persisted in the report."""
    correlation_id = uuid4()
    context = GuardrailsContext(
        tenant_id=uuid4(),
        actor_principal_id=uuid4(),
        action="create",
        space_kind="personal",
        subspace_kind="staging",
        correlation_id=correlation_id,
    )

    resource_id = await setup_resource_and_tenant(
        db_session, str(context.tenant_id), str(context.actor_principal_id)
    )
    target_id = str(uuid4())

    report = await engine.validate_at_gate(
        db=db_session,
        scope="resource",
        target_id=target_id,
        resource_id=resource_id,
        context=context,
        target_snapshot={},
    )

    # Verify correlation_id in report
    assert report.correlation_id == str(correlation_id)

    # Verify persisted in database
    result = await db_session.execute(
        text("SELECT correlation_id FROM validation_reports WHERE report_id = :id"),
        {"id": report.report_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == str(correlation_id)
