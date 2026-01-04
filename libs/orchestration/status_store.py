"""StatusStore for execution metadata storage.

Ported from: optaic-v0/dev_tools/src/data/status_store.py
Adapted to use SQLAlchemy async sessions instead of raw SQLite.

This module provides persistent storage for execution metadata:
- Pipeline run status (running, success, error)
- Last data date and row counts
- Error messages and source delay detection
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.db.models.quant import DatasetStatus


@dataclass
class DatasetStatusRecord:
    """Execution status record for a dataset instance.

    Tracks the execution state of a dataset's pipeline, including:
    - Pipeline run timing and status
    - Data freshness (last_data_date)
    - Error information
    - Source delay detection (for external data sources)
    """

    dataset_id: UUID
    last_pipeline_run: Optional[datetime] = None
    last_pipeline_status: Optional[str] = None  # "running", "success", "error", "empty"
    last_data_date: Optional[date] = None
    last_source_check: Optional[datetime] = None
    source_delay_detected: bool = False
    error_message: Optional[str] = None
    rows_processed: Optional[int] = None
    updated_at: Optional[datetime] = None


class StatusStore:
    """Persistent execution metadata storage.

    Provides methods to track pipeline execution status for dataset instances.
    Status is stored in the dataset_status table and queried by the DAG builder
    and RunExecutionService to determine which datasets need refresh.

    Example usage:
        status_store = StatusStore(session)

        # Mark run start
        await status_store.mark_run_start(dataset_id)

        try:
            # Execute pipeline...
            result = await pipeline.run()

            # Mark success
            await status_store.mark_run_success(
                dataset_id,
                last_data_date=result.last_date,
                rows_processed=result.row_count,
            )
        except Exception as e:
            # Mark error
            await status_store.mark_run_error(dataset_id, str(e))
    """

    def __init__(self, session: "AsyncSession") -> None:
        """Initialize StatusStore with database session.

        Args:
            session: SQLAlchemy async session
        """
        self._session = session

    async def get_status(self, dataset_id: UUID) -> Optional[DatasetStatusRecord]:
        """Get status record for a dataset.

        Args:
            dataset_id: Dataset instance resource ID

        Returns:
            DatasetStatusRecord if exists, None otherwise
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetStatus

        stmt = select(DatasetStatus).where(DatasetStatus.dataset_id == dataset_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            return None

        return DatasetStatusRecord(
            dataset_id=row.dataset_id,
            last_pipeline_run=row.last_pipeline_run,
            last_pipeline_status=row.last_pipeline_status,
            last_data_date=row.last_data_date,
            last_source_check=row.last_source_check,
            source_delay_detected=row.source_delay_detected,
            error_message=row.error_message,
            rows_processed=row.rows_processed,
            updated_at=row.updated_at,
        )

    async def mark_run_start(self, dataset_id: UUID) -> None:
        """Mark the start of a pipeline run.

        Args:
            dataset_id: Dataset instance resource ID

        Note:
            Uses flush() instead of commit() to allow caller to manage transactions.
        """

        status = await self._get_or_create(dataset_id)
        status.last_pipeline_run = datetime.now(UTC)
        status.last_pipeline_status = "running"
        status.error_message = None
        status.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_run_success(
        self,
        dataset_id: UUID,
        *,
        last_data_date: Optional[date] = None,
        rows_processed: Optional[int] = None,
        source_delay_detected: bool = False,
    ) -> None:
        """Mark successful completion of a pipeline run.

        Args:
            dataset_id: Dataset instance resource ID
            last_data_date: Latest date in the dataset
            rows_processed: Number of rows processed in this run
            source_delay_detected: Whether source data delay was detected

        Note:
            Uses flush() instead of commit() to allow caller to manage transactions.
        """
        status = await self._get_or_create(dataset_id)
        status.last_pipeline_status = "success"
        status.last_data_date = last_data_date
        status.rows_processed = rows_processed
        status.source_delay_detected = source_delay_detected
        status.error_message = None
        status.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_run_error(
        self,
        dataset_id: UUID,
        error_message: str,
    ) -> None:
        """Mark pipeline run as failed.

        Args:
            dataset_id: Dataset instance resource ID
            error_message: Error description

        Note:
            Uses flush() instead of commit() to allow caller to manage transactions.
        """
        status = await self._get_or_create(dataset_id)
        status.last_pipeline_status = "error"
        status.error_message = error_message
        status.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_run_empty(self, dataset_id: UUID) -> None:
        """Mark pipeline run as completed with no new data.

        Args:
            dataset_id: Dataset instance resource ID

        Note:
            Uses flush() instead of commit() to allow caller to manage transactions.
        """
        status = await self._get_or_create(dataset_id)
        status.last_pipeline_status = "empty"
        status.error_message = None
        status.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_source_check(
        self,
        dataset_id: UUID,
        delay_detected: bool,
    ) -> None:
        """Record a source availability check.

        Args:
            dataset_id: Dataset instance resource ID
            delay_detected: Whether source data is delayed

        Note:
            Uses flush() instead of commit() to allow caller to manage transactions.
        """
        status = await self._get_or_create(dataset_id)
        status.last_source_check = datetime.now(UTC)
        status.source_delay_detected = delay_detected
        status.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def get_stale_datasets(
        self,
        tenant_id: UUID,
        *,
        max_age_hours: int = 24,
    ) -> list[DatasetStatusRecord]:
        """Get datasets that are stale or have errors.

        Args:
            tenant_id: Tenant ID to filter by
            max_age_hours: Consider stale if not run within this many hours

        Returns:
            List of stale dataset status records
        """
        from datetime import timedelta

        from sqlalchemy import or_, select

        from libs.db.models.quant import DatasetStatus

        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

        stmt = select(DatasetStatus).where(
            DatasetStatus.tenant_id == tenant_id,
            or_(
                DatasetStatus.last_pipeline_run.is_(None),
                DatasetStatus.last_pipeline_run < cutoff,
                DatasetStatus.last_pipeline_status == "error",
            ),
        )

        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        return [
            DatasetStatusRecord(
                dataset_id=row.dataset_id,
                last_pipeline_run=row.last_pipeline_run,
                last_pipeline_status=row.last_pipeline_status,
                last_data_date=row.last_data_date,
                last_source_check=row.last_source_check,
                source_delay_detected=row.source_delay_detected,
                error_message=row.error_message,
                rows_processed=row.rows_processed,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def _get_or_create(self, dataset_id: UUID) -> "DatasetStatus":
        """Get existing status record or create new one.

        Args:
            dataset_id: Dataset instance resource ID

        Returns:
            DatasetStatus model instance
        """
        from sqlalchemy import select

        from libs.db.models.resource import Resource
        from libs.db.models.quant import DatasetStatus

        stmt = select(DatasetStatus).where(DatasetStatus.dataset_id == dataset_id)
        result = await self._session.execute(stmt)
        status = result.scalar_one_or_none()

        if not status:
            # Get tenant_id from the resource
            resource = await self._session.get(Resource, dataset_id)
            if not resource:
                raise ValueError(f"Dataset resource {dataset_id} not found")

            status = DatasetStatus(
                dataset_id=dataset_id,
                tenant_id=resource.tenant_id,
            )
            self._session.add(status)

        return status
