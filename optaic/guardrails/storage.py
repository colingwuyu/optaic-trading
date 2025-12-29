"""Storage layer for guardrails persistence.

Provides storage classes for ContractBundles and ValidationReports
with async SQLAlchemy support.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from optaic.guardrails.contracts.base import ContractBundle
from optaic.guardrails.reports.models import ValidationReport
from optaic.guardrails.utils import canonical_dumps

if TYPE_CHECKING:
    pass


class ContractBundleStore:
    """Storage operations for ContractBundles.

    Manages the lifecycle of contract bundles per resource,
    ensuring only one active bundle exists at a time.
    """

    @staticmethod
    async def upsert_active_bundle(
        db: AsyncSession,
        bundle: ContractBundle,
    ) -> None:
        """Insert or replace the active bundle for a resource.

        Deactivates any existing active bundle for the resource,
        then inserts the new bundle as active.

        Args:
            db: Async database session.
            bundle: The ContractBundle to upsert.
        """
        from libs.db.models.guardrails import ResourceContractBundle

        # Deactivate any existing active bundle for this resource
        await db.execute(
            update(ResourceContractBundle)
            .where(
                and_(
                    ResourceContractBundle.resource_id == bundle.resource_id,
                    ResourceContractBundle.is_active == True,  # noqa: E712
                )
            )
            .values(is_active=False)
        )

        # Insert new active bundle
        record = ResourceContractBundle(
            bundle_id=bundle.bundle_id,
            resource_id=bundle.resource_id,
            resource_version_id=bundle.resource_version_id,
            created_by=bundle.created_by,
            created_at=bundle.created_at,
            bundle_json=canonical_dumps(bundle),
            is_active=True,
        )
        db.add(record)
        await db.flush()

    @staticmethod
    async def get_active_bundle(
        db: AsyncSession,
        resource_id: str,
    ) -> ContractBundle | None:
        """Get the active contract bundle for a resource.

        Args:
            db: Async database session.
            resource_id: The resource ID to look up.

        Returns:
            The active ContractBundle, or None if none exists.
        """
        from libs.db.models.guardrails import ResourceContractBundle

        result = await db.execute(
            select(ResourceContractBundle).where(
                and_(
                    ResourceContractBundle.resource_id == resource_id,
                    ResourceContractBundle.is_active == True,  # noqa: E712
                )
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None

        return ContractBundle.model_validate_json(record.bundle_json)


class ValidationReportStore:
    """Storage operations for ValidationReports.

    Reports are immutable once created. This store handles
    insertion and querying of validation history.
    """

    @staticmethod
    async def insert_report(
        db: AsyncSession,
        report: ValidationReport,
    ) -> None:
        """Insert a validation report.

        Args:
            db: Async database session.
            report: The ValidationReport to insert.
        """
        from libs.db.models.guardrails import ValidationReportRecord

        record = ValidationReportRecord(
            report_id=report.report_id,
            scope=report.scope,
            target_id=report.target_id,
            ok=report.ok,
            enforced_as=report.enforced_as,
            created_by=report.created_by,
            created_at=report.created_at,
            correlation_id=report.correlation_id,
            report_json=canonical_dumps(report),
        )
        db.add(record)
        await db.flush()

    @staticmethod
    async def list_reports(
        db: AsyncSession,
        scope: str | None = None,
        target_id: str | None = None,
        limit: int = 50,
    ) -> list[ValidationReport]:
        """List validation reports with optional filtering.

        Args:
            db: Async database session.
            scope: Optional filter by scope (resource, run, promotion, merge).
            target_id: Optional filter by target ID.
            limit: Maximum number of reports to return.

        Returns:
            List of ValidationReports, ordered by created_at descending.
        """
        from libs.db.models.guardrails import ValidationReportRecord

        query = select(ValidationReportRecord)

        conditions = []
        if scope is not None:
            conditions.append(ValidationReportRecord.scope == scope)
        if target_id is not None:
            conditions.append(ValidationReportRecord.target_id == target_id)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(desc(ValidationReportRecord.created_at)).limit(limit)

        result = await db.execute(query)
        records = result.scalars().all()

        return [
            ValidationReport.model_validate_json(record.report_json)
            for record in records
        ]
