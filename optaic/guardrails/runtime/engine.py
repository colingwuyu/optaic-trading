"""Runtime engine for guardrails enforcement."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from optaic.guardrails.contracts.registry import ContractRegistry, get_default_registry
from optaic.guardrails.enforcement.policy import compute_effective_enforcement
from optaic.guardrails.reports.models import ValidationReport
from optaic.guardrails.runtime.context import GuardrailsContext
from optaic.guardrails.storage import ContractBundleStore, ValidationReportStore
from optaic.guardrails.validators.base import ValidationIssue


class GuardrailsBlocked(Exception):
    """Raised when an action is blocked by guardrails."""

    def __init__(self, report_id: str, issues: list[ValidationIssue]) -> None:
        self.report_id = report_id
        self.issues = issues
        issue_msg = f"{len(issues)} issues found"
        if issues:
            issue_msg += f": {issues[0].message}"
            if len(issues) > 1:
                issue_msg += "..."
        super().__init__(
            f"Guardrails blocked action (Report ID: {report_id}). {issue_msg}"
        )


class GuardrailsEngine:
    """Engine for checking guardrails at lifecycle gates."""

    def __init__(
        self,
        registry: Optional[ContractRegistry] = None,
    ) -> None:
        """Initialize the guardrails engine.

        Args:
            registry: Optional ContractRegistry (defaults to global instance).
        """
        self.registry = registry or get_default_registry()

    async def validate_at_gate(
        self,
        db: AsyncSession,
        scope: str,
        target_id: str,
        resource_id: str,
        context: GuardrailsContext,
        target_snapshot: Any,
    ) -> ValidationReport:
        """Validate an action at a lifecycle gate.

        Loads the active contract bundle for the resource, validates the target
        snapshot against it, computes enforcement policy, persists the report,
        and emits events.

        If enforcement is "block" and there are issues, raises GuardrailsBlocked.

        Args:
            db: Async database session.
            scope: Scope of validation (resource, run, etc.).
            target_id: ID of the target being validated.
            resource_id: ID of the resource (to load bundle).
            context: Contextual information for validation/policy.
            target_snapshot: The data snapshot to validate.

        Returns:
            The created ValidationReport.

        Raises:
            GuardrailsBlocked: If the action is blocked by policy.
        """
        # 1. Load active bundle
        bundle = await ContractBundleStore.get_active_bundle(db, resource_id)

        # If no bundle, return passing report
        if bundle is None:
            # Create a "passing" report with no contracts
            report = ValidationReport(
                report_id=str(uuid4()),
                scope=scope,
                target_id=target_id,
                ok=True,
                enforced_as="warn",  # Default when no contracts
                issues=[],
                contract_hashes=[],
                created_by=str(context.actor_principal_id),
                correlation_id=str(context.correlation_id)
                if context.correlation_id
                else None,
            )
            # We still persist this "empty" validation
            await self._persist_and_emit(db, report, context, resource_id)
            return report

        # 2. Validate using registry
        validation_context = {
            "tenant_id": str(context.tenant_id),
            "actor_principal_id": str(context.actor_principal_id),
            "space_kind": context.space_kind,
            "subspace_kind": context.subspace_kind,
            "action": context.action,
            "extra": context.extra,
        }
        issues = self.registry.validate_bundle(
            bundle, validation_context, target_snapshot
        )

        # 3. Compute enforcement policy
        # Collect max hint from contracts that have issues (or all?)
        # Policy typically aggregates hints. We'll take the "strongest" hint from contracts
        # that actually produced issues, or default to warn if no issues?
        # Actually policy logic uses the bundle-level hints or contract-level hints.
        # Since we don't have per-issue contract info here easily without iterating,
        # let's assume we take the strongest hint from *all* contracts in the bundle
        # as a conservative approach, OR assume "warn" and let policy override.

        # A simple strategy: check if ANY contract says "block", use block hint.
        bundle_hint = "warn"
        for contract in bundle.contracts:
            if contract.enforcement_hint == "block":
                bundle_hint = "block"
                break

        subspace = context.subspace_kind or "custom"
        enforced_as = compute_effective_enforcement(
            subspace, context.action, bundle_hint
        )

        ok = len(issues) == 0

        # If we have issues but policy says "warn", we are still "ok" execution-wise (don't block)
        # But report.ok should reflect if validation passed.
        # Wait, report.ok usually means "validation passed without errors".
        # Whether we BLOCK is separate (enforced_as='block' AND report.ok=False).

        report = ValidationReport(
            report_id=str(uuid4()),
            scope=scope,
            target_id=target_id,
            ok=ok,
            enforced_as=enforced_as,
            issues=issues,
            contract_hashes=[c.contract_hash for c in bundle.contracts],
            created_by=str(context.actor_principal_id),
            correlation_id=str(context.correlation_id)
            if context.correlation_id
            else None,
        )

        # 4 & 5. Persist and Emit
        await self._persist_and_emit(db, report, context, resource_id)

        # 6. Block if needed
        if not ok and enforced_as == "block":
            raise GuardrailsBlocked(report.report_id, issues)

        return report

    async def _persist_and_emit(
        self,
        db: AsyncSession,
        report: ValidationReport,
        context: GuardrailsContext,
        resource_id: str,
    ) -> None:
        """Persist report and emit activity event."""
        # Persist report
        await ValidationReportStore.insert_report(db, report)

        # Emit event
        event_name = "guardrails.validated"
        if not report.ok and report.enforced_as == "block":
            event_name = "guardrails.blocked"

        envelope = ActivityEnvelope(
            tenant_id=context.tenant_id,
            actor_principal_id=context.actor_principal_id,
            resource_id=UUID(resource_id),
            resource_type="ValidationReport",  # Or the target resource type?
            # Using "ValidationReport" as resource_type effectively associates this activity with the *report*
            # but we want it visible on the *resource*.
            # ActivityEnvelope requires resource_id.
            action=event_name,
            payload={
                "report_id": report.report_id,
                "scope": report.scope,
                "target_id": report.target_id,
                "ok": report.ok,
                "enforced_as": report.enforced_as,
                "issue_count": len(report.issues),
                "summary": f"{len(report.issues)} issues found",
            },
            correlation_id=context.correlation_id or uuid4(),
        )

        await record_activity_with_outbox(db, envelope)
