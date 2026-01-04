"""Integration tests for guardrails enforcement in resource operations.

Tests the complete guardrails integration flow:
- Contract bundle loading from database
- Validation at lifecycle gates (create, update, promote)
- Enforcement policy computation (warn vs block)
- ValidationReport persistence
- Activity emission for validation events
- GuardrailsBlocked exception handling (403 response)

All tests use real database sessions from the sandbox infrastructure.
NO MOCKS - tests verify actual database operations and guardrails logic.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.models.activity import Activity
from libs.db.models.resource import Resource
from optaic.guardrails.contracts.base import (
    ContractBundle,
    ContractInstance,
    ContractRef,
)
from optaic.guardrails.contracts.registry import ContractRegistry
from optaic.guardrails.runtime.context import GuardrailsContext
from optaic.guardrails.runtime.engine import GuardrailsBlocked, GuardrailsEngine
from optaic.guardrails.storage import ContractBundleStore, ValidationReportStore
from optaic.guardrails.utils import contract_hash
from optaic.guardrails.validators.base import ContractValidator, ValidationIssue


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
            "name": "Guardrails Test Tenant",
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
            "display_name": "Guardrails Test User",
            "created_at": utcnow_iso(),
        },
    )
    await db_session.flush()
    return tenant_id, principal_id


async def create_test_resource(
    db_session: AsyncSession,
    tenant_id,
    principal_id,
    name: str,
    resource_type: str = "DatasetInstance",
) -> Resource:
    """Create a test resource and return it."""
    resource_id = uuid4()

    resource = Resource(
        id=resource_id,
        tenant_id=tenant_id,
        owner_principal_id=principal_id,
        type=resource_type,
        name=name,
        status="active",
    )
    db_session.add(resource)
    await db_session.flush()

    return resource


# ---------------------------------------------------------------------------
# Custom test validators (ContractValidator subclasses)
# ---------------------------------------------------------------------------


class AlwaysPassValidator(ContractValidator):
    """A validator that always passes."""

    @property
    def name(self) -> str:
        return "always_pass"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        return []


class AlwaysFailValidator(ContractValidator):
    """A validator that always fails with a configurable message."""

    @property
    def name(self) -> str:
        return "always_fail"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        # Get message from contract config
        import json

        config = contract_instance.config_json
        if isinstance(config, str):
            config = json.loads(config)
        message = config.get("message", "Validation failed")

        return [
            ValidationIssue(
                severity="error",
                code="TEST_FAILURE",
                message=message,
                path=None,
            )
        ]


class SignalBoundsValidator(ContractValidator):
    """Validator that checks signal values are within configured bounds."""

    @property
    def name(self) -> str:
        return "signal_bounds"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        import json

        if not isinstance(target_snapshot, dict):
            return []

        config = contract_instance.config_json
        if isinstance(config, str):
            config = json.loads(config)

        min_val = config.get("min", -1.0)
        max_val = config.get("max", 1.0)
        signal_value = target_snapshot.get("signal_value")

        if signal_value is None:
            return []

        issues = []
        if signal_value < min_val:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SIGNAL_BELOW_MIN",
                    message=f"Signal must be >= {min_val}, got {signal_value}",
                    path="signal_value",
                )
            )
        if signal_value > max_val:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SIGNAL_ABOVE_MAX",
                    message=f"Signal must be <= {max_val}, got {signal_value}",
                    path="signal_value",
                )
            )

        return issues


class PortfolioWeightValidator(ContractValidator):
    """Validator that checks portfolio weights sum to 1.0."""

    @property
    def name(self) -> str:
        return "portfolio_weights"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        import json

        if not isinstance(target_snapshot, dict):
            return []

        config = contract_instance.config_json
        if isinstance(config, str):
            config = json.loads(config)

        tolerance = config.get("tolerance", 0.01)
        weights = target_snapshot.get("weights", {})

        if not weights:
            return []

        total = sum(weights.values())
        if abs(total - 1.0) > tolerance:
            return [
                ValidationIssue(
                    severity="error",
                    code="INVALID_WEIGHT_SUM",
                    message=f"Portfolio weights must sum to 1.0, got {total:.2f}",
                    path="weights",
                )
            ]
        return []


def create_test_registry() -> ContractRegistry:
    """Create a ContractRegistry with test validators and contract kinds."""
    registry = ContractRegistry()

    # Register test validators
    registry.register_validator("always_pass", AlwaysPassValidator)
    registry.register_validator("always_fail", AlwaysFailValidator)
    registry.register_validator("signal_bounds", SignalBoundsValidator)
    registry.register_validator("portfolio_weights", PortfolioWeightValidator)

    # Register contract kinds with their schemas
    registry.register_contract_kind(
        kind="test",
        version="1.0.0",
        json_schema={"type": "object"},
        default_validator="always_pass",
    )

    registry.register_contract_kind(
        kind="test.fail",
        version="1.0.0",
        json_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        default_validator="always_fail",
    )

    registry.register_contract_kind(
        kind="signal.bounds",
        version="1.0.0",
        json_schema={
            "type": "object",
            "properties": {
                "min": {"type": "number"},
                "max": {"type": "number"},
            },
        },
        default_validator="signal_bounds",
    )

    registry.register_contract_kind(
        kind="portfolio.weights",
        version="1.0.0",
        json_schema={
            "type": "object",
            "properties": {
                "tolerance": {"type": "number"},
            },
        },
        default_validator="portfolio_weights",
    )

    return registry


def create_contract_instance(
    kind: str,
    name: str,
    version: str = "1.0.0",
    config: dict[str, Any] | None = None,
    enforcement_hint: str = "warn",
) -> ContractInstance:
    """Helper to create a ContractInstance with proper hash."""
    import json

    config_json = json.dumps(config or {})
    ref = ContractRef(
        contract_kind=kind,
        contract_name=name,
        version=version,
        json_schema="{}",
    )
    hash_value = contract_hash(ref, config_json)

    return ContractInstance(
        ref=ref,
        config_json=config_json,
        contract_hash=hash_value,
        enforcement_hint=enforcement_hint,
    )


@pytest.mark.asyncio
class TestGuardrailsEngineValidation:
    """Tests for GuardrailsEngine.validate_at_gate."""

    async def test_no_bundle_returns_passing_report(self, db_session: AsyncSession):
        """When no contract bundle exists, returns a passing report."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "No Bundle Resource"
        )

        registry = create_test_registry()
        engine = GuardrailsEngine(registry=registry)

        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="custom",
            action="resource.create",
        )

        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"name": "Test"},
        )

        assert report.ok is True
        assert report.enforced_as == "warn"  # Default when no contracts
        assert len(report.issues) == 0

    async def test_passing_validation_persists_report(self, db_session: AsyncSession):
        """Passing validation persists ValidationReport to database."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Pass Validation Resource"
        )

        # Create registry with passing validator
        registry = create_test_registry()

        # Create and store a contract bundle
        contract = create_contract_instance(
            kind="test",
            name="always_pass",
            enforcement_hint="warn",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)

        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="custom",
            action="resource.update",
        )

        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"name": "Updated"},
        )

        assert report.ok is True

        # Verify report was persisted
        reports = await ValidationReportStore.list_reports(
            db_session, target_id=str(resource.id)
        )
        assert len(reports) >= 1
        assert any(r.report_id == report.report_id for r in reports)

    async def test_failing_validation_with_warn_does_not_raise(
        self, db_session: AsyncSession
    ):
        """Failing validation with warn enforcement does not raise exception."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Warn Validation Resource"
        )

        # Create registry with failing validator
        registry = create_test_registry()

        # Create bundle with warn enforcement
        contract = create_contract_instance(
            kind="test.fail",
            name="always_fail_warn",
            config={"message": "Test failure"},
            enforcement_hint="warn",  # Warn, don't block
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)

        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="custom",
            action="resource.update",
        )

        # Should not raise, even though validation fails
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"name": "Bad Data"},
        )

        assert report.ok is False  # Validation failed
        assert report.enforced_as == "warn"  # But only warned
        assert len(report.issues) == 1
        assert report.issues[0].message == "Test failure"

    async def test_failing_validation_with_block_raises_exception(
        self, db_session: AsyncSession
    ):
        """Failing validation with block enforcement raises GuardrailsBlocked."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Block Validation Resource"
        )

        # Create registry with failing validator
        registry = create_test_registry()

        # Create bundle with block enforcement
        contract = create_contract_instance(
            kind="test.fail",
            name="blocking_fail",
            config={"message": "Critical validation failure"},
            enforcement_hint="block",  # Block, don't just warn
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)

        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",  # Official subspace typically blocks
            action="resource.promote",
        )

        # Should raise GuardrailsBlocked
        with pytest.raises(GuardrailsBlocked) as exc_info:
            await engine.validate_at_gate(
                db=db_session,
                scope="resource",
                target_id=str(resource.id),
                resource_id=str(resource.id),
                context=context,
                target_snapshot={"name": "Invalid"},
            )

        assert len(exc_info.value.issues) == 1
        assert "Critical validation failure" in exc_info.value.issues[0].message

        # Verify report was still persisted (for audit trail)
        report_id = exc_info.value.report_id
        reports = await ValidationReportStore.list_reports(
            db_session, target_id=str(resource.id)
        )
        assert any(r.report_id == report_id for r in reports)
        blocked_report = next(r for r in reports if r.report_id == report_id)
        assert blocked_report.ok is False

    async def test_emits_activity_on_validation(self, db_session: AsyncSession):
        """Validation emits guardrails.validated activity."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Activity Emission Resource"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="test",
            name="pass_activity_test",
            enforcement_hint="warn",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)

        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="custom",
            action="resource.create",
        )

        await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"value": 100},
        )

        # Verify activity was emitted
        stmt = select(Activity).where(
            Activity.resource_id == resource.id,
            Activity.action == "guardrails.validated",
        )
        result = await db_session.execute(stmt)
        activity = result.scalar_one_or_none()

        assert activity is not None
        assert activity.payload["ok"] is True
        assert "report_id" in activity.payload

    async def test_emits_blocked_activity_on_block(self, db_session: AsyncSession):
        """Blocked validation emits guardrails.blocked activity."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Blocked Activity Resource"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="test.fail",
            name="blocker",
            config={"message": "Blocked"},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)

        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="resource.promote",
        )

        with pytest.raises(GuardrailsBlocked):
            await engine.validate_at_gate(
                db=db_session,
                scope="resource",
                target_id=str(resource.id),
                resource_id=str(resource.id),
                context=context,
                target_snapshot={},
            )

        # Verify blocked activity was emitted
        stmt = select(Activity).where(
            Activity.resource_id == resource.id,
            Activity.action == "guardrails.blocked",
        )
        result = await db_session.execute(stmt)
        activity = result.scalar_one_or_none()

        assert activity is not None
        assert activity.payload["ok"] is False


@pytest.mark.asyncio
class TestConditionalValidation:
    """Tests for validators with conditional logic."""

    async def test_signal_bounds_validation_passes(self, db_session: AsyncSession):
        """Signal within bounds passes validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Signal Bounds Pass"
        )

        registry = create_test_registry()

        # Signal must be between -1 and 1
        contract = create_contract_instance(
            kind="signal.bounds",
            name="alpha_bounds",
            config={"min": -1.0, "max": 1.0},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="signal.publish",
        )

        # Signal within bounds - should pass
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",  # Use valid scope
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"signal_value": 0.5},
        )

        assert report.ok is True

    async def test_signal_bounds_validation_fails(self, db_session: AsyncSession):
        """Signal outside bounds fails validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Signal Bounds Fail"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="signal.bounds",
            name="alpha_bounds",
            config={"min": -1.0, "max": 1.0},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="signal.publish",
        )

        # Signal outside bounds - should fail and block
        with pytest.raises(GuardrailsBlocked) as exc_info:
            await engine.validate_at_gate(
                db=db_session,
                scope="resource",  # Use valid scope
                target_id=str(resource.id),
                resource_id=str(resource.id),
                context=context,
                target_snapshot={"signal_value": 1.5},  # Exceeds max
            )

        assert "Signal must be <= 1.0" in exc_info.value.issues[0].message

    async def test_portfolio_weight_validation(self, db_session: AsyncSession):
        """Portfolio weight constraints validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Portfolio Weights"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="portfolio.weights",
            name="weight_sum",
            config={"tolerance": 0.01},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="portfolio.rebalance",
        )

        # Valid weights (sum to 1.0)
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",  # Use valid scope
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"weights": {"AAPL": 0.4, "GOOGL": 0.3, "MSFT": 0.3}},
        )
        assert report.ok is True

        # Invalid weights (sum to 1.2)
        with pytest.raises(GuardrailsBlocked) as exc_info:
            await engine.validate_at_gate(
                db=db_session,
                scope="resource",  # Use valid scope
                target_id=str(resource.id),
                resource_id=str(resource.id),
                context=context,
                target_snapshot={"weights": {"AAPL": 0.5, "GOOGL": 0.4, "MSFT": 0.3}},
            )

        assert "sum to 1.0" in exc_info.value.issues[0].message


@pytest.mark.asyncio
class TestMultipleContractBundles:
    """Tests for handling multiple contracts in a bundle."""

    async def test_all_contracts_must_pass(self, db_session: AsyncSession):
        """All contracts in a bundle must pass for validation to succeed."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Multi Contract Resource"
        )

        registry = create_test_registry()

        contract1 = create_contract_instance(
            kind="test",
            name="pass1",
            enforcement_hint="warn",
        )
        contract2 = create_contract_instance(
            kind="test",
            name="pass2",
            enforcement_hint="warn",
        )
        contract3 = create_contract_instance(
            kind="test.fail",
            name="fail",
            config={"message": "Contract 3 failed"},
            enforcement_hint="block",
        )

        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract1, contract2, contract3],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="resource.promote",
        )

        # Should fail because one contract fails
        with pytest.raises(GuardrailsBlocked):
            await engine.validate_at_gate(
                db=db_session,
                scope="resource",
                target_id=str(resource.id),
                resource_id=str(resource.id),
                context=context,
                target_snapshot={},
            )

    async def test_only_active_bundle_is_used(self, db_session: AsyncSession):
        """Only the active bundle is used for validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Active Bundle Resource"
        )

        registry = create_test_registry()

        # First insert a failing bundle (will be deactivated)
        failing_contract = create_contract_instance(
            kind="test.fail",
            name="should_not_be_used",
            config={"message": "Should not be used"},
            enforcement_hint="block",
        )
        failing_bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[failing_contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, failing_bundle)

        # Then insert a passing bundle (becomes active, deactivates the first)
        passing_contract = create_contract_instance(
            kind="test",
            name="passing",
            enforcement_hint="warn",
        )
        active_bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[passing_contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, active_bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="custom",
            action="resource.update",
        )

        # Should pass because only active bundle is used
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={},
        )

        assert report.ok is True


@pytest.mark.asyncio
class TestEdgeCasesAndBoundaries:
    """Tests for edge cases, boundary values, and corner cases."""

    async def test_signal_below_minimum_fails(self, db_session: AsyncSession):
        """Signal below minimum bound fails validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Signal Below Min"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="signal.bounds",
            name="alpha_bounds",
            config={"min": -1.0, "max": 1.0},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="signal.publish",
        )

        # Signal below min - should fail
        with pytest.raises(GuardrailsBlocked) as exc_info:
            await engine.validate_at_gate(
                db=db_session,
                scope="resource",
                target_id=str(resource.id),
                resource_id=str(resource.id),
                context=context,
                target_snapshot={"signal_value": -1.5},  # Below min
            )

        assert "Signal must be >= -1.0" in exc_info.value.issues[0].message

    async def test_signal_at_boundary_passes(self, db_session: AsyncSession):
        """Signal exactly at boundary values passes validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Signal At Boundary"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="signal.bounds",
            name="alpha_bounds",
            config={"min": -1.0, "max": 1.0},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="signal.publish",
        )

        # At minimum boundary
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"signal_value": -1.0},
        )
        assert report.ok is True

        # At maximum boundary
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"signal_value": 1.0},
        )
        assert report.ok is True

    async def test_empty_bundle_passes(self, db_session: AsyncSession):
        """Bundle with no contracts passes validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Empty Bundle Resource"
        )

        registry = create_test_registry()

        # Create empty bundle
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[],  # No contracts
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="custom",
            action="resource.update",
        )

        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"any": "data"},
        )

        assert report.ok is True

    async def test_negative_portfolio_weight_long_short(self, db_session: AsyncSession):
        """Long-short portfolio with negative weights summing to 1.0 passes."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Long-Short Portfolio"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="portfolio.weights",
            name="weight_sum",
            config={"tolerance": 0.01},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="portfolio.rebalance",
        )

        # Long-short portfolio: AAPL +60%, GOOGL -10% (short), MSFT +50% = 100%
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"weights": {"AAPL": 0.6, "GOOGL": -0.1, "MSFT": 0.5}},
        )
        assert report.ok is True

    async def test_weight_sum_within_tolerance(self, db_session: AsyncSession):
        """Weights sum within tolerance passes validation."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Weight Tolerance"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="portfolio.weights",
            name="weight_sum",
            config={"tolerance": 0.02},  # 2% tolerance
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="portfolio.rebalance",
        )

        # Sum = 0.99, within 0.02 tolerance of 1.0
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"weights": {"AAPL": 0.33, "GOOGL": 0.33, "MSFT": 0.33}},
        )
        assert report.ok is True

    async def test_missing_signal_value_passes(self, db_session: AsyncSession):
        """When signal_value is not in snapshot, validation passes (no data to check)."""
        tenant_id, principal_id = await create_tenant_and_principal(db_session)
        resource = await create_test_resource(
            db_session, tenant_id, principal_id, "Missing Signal Value"
        )

        registry = create_test_registry()

        contract = create_contract_instance(
            kind="signal.bounds",
            name="alpha_bounds",
            config={"min": -1.0, "max": 1.0},
            enforcement_hint="block",
        )
        bundle = ContractBundle(
            bundle_id=str(uuid4()),
            resource_id=str(resource.id),
            created_by=str(principal_id),
            contracts=[contract],
        )
        await ContractBundleStore.upsert_active_bundle(db_session, bundle)

        engine = GuardrailsEngine(registry=registry)
        context = GuardrailsContext(
            tenant_id=tenant_id,
            actor_principal_id=principal_id,
            space_kind="research",
            subspace_kind="official",
            action="signal.publish",
        )

        # No signal_value in snapshot - validator returns empty issues
        report = await engine.validate_at_gate(
            db=db_session,
            scope="resource",
            target_id=str(resource.id),
            resource_id=str(resource.id),
            context=context,
            target_snapshot={"other_field": 123},
        )
        assert report.ok is True
