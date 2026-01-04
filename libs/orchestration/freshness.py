"""Freshness checking for dataset resources.

Provides staleness detection and freshness calculation based on:
- UpdateFrequency configuration (daily, weekly, etc.)
- Last pipeline run status
- Last data date vs expected date
- Source delay detection

This module is the core of the "smart execution" feature where we:
- Skip execution if data is already fresh
- Detect when source data is delayed
- Calculate expected data dates based on frequency

Ported from: optaic-v0/dev_tools/src/data/api.py (freshness logic)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .status_store import StatusStore


class DatasetStatus(str, Enum):
    """Status of a dataset's data freshness."""

    NOT_INITIALIZED = "not_initialized"  # No data exists yet
    READY = "ready"  # Current and valid
    STALE = "stale"  # Outdated, needs refresh
    STALE_SOURCE_DELAYED = "stale_source_delayed"  # Source has no new data yet
    ERROR = "error"  # Pipeline failed


@dataclass
class UpdateFrequency:
    """Defines expected update schedule for a dataset.

    Used to calculate whether data is stale based on its expected
    update frequency and configured grace period.

    Examples:
        # Daily data with 1 day grace period
        freq = UpdateFrequency(frequency="daily", grace_period_days=1)

        # Weekly data on Monday
        freq = UpdateFrequency(frequency="weekly", day_of_week=0)

        # Business day data (skip weekends)
        freq = UpdateFrequency(
            frequency="daily",
            business_days_only=True,
            grace_period_days=1
        )
    """

    frequency: str = "daily"  # "daily", "weekly", "monthly", "quarterly", "irregular"
    grace_period_days: int = 0  # Tolerance for late arrivals
    business_days_only: bool = False  # Skip weekends/holidays
    day_of_week: Optional[int] = None  # For weekly: 0=Monday, 6=Sunday
    day_of_month: Optional[int] = None  # For monthly: 1-31

    def get_expected_date(self, as_of: date) -> date:
        """Calculate expected latest data date based on frequency.

        Args:
            as_of: Reference date (typically today)

        Returns:
            Expected latest data date
        """
        if self.frequency == "daily":
            if self.business_days_only:
                return self._get_previous_business_day(as_of)
            return as_of - timedelta(days=1)

        if self.frequency == "weekly":
            # Find the most recent occurrence of day_of_week
            dow = self.day_of_week or 0  # Default to Monday
            days_since = (as_of.weekday() - dow) % 7
            if days_since == 0:
                days_since = 7  # Previous occurrence
            return as_of - timedelta(days=days_since)

        if self.frequency == "monthly":
            # Previous month's data
            first_of_month = as_of.replace(day=1)
            last_of_prev_month = first_of_month - timedelta(days=1)
            return last_of_prev_month

        if self.frequency == "quarterly":
            # Previous quarter's data
            # Current quarter: Q1=0, Q2=1, Q3=2, Q4=3
            quarter = (as_of.month - 1) // 3
            if quarter == 0:
                # In Q1 -> expect Q4 of previous year (Dec 31)
                return date(as_of.year - 1, 12, 31)
            else:
                # Previous quarter end months: Q1=Mar(3), Q2=Jun(6), Q3=Sep(9)
                prev_quarter_end_month = quarter * 3
                # Get last day of that month
                if prev_quarter_end_month == 12:
                    return date(as_of.year, 12, 31)
                # Use next month's first day - 1
                return date(as_of.year, prev_quarter_end_month + 1, 1) - timedelta(
                    days=1
                )

        # "irregular" - no expected date
        return as_of

    def is_stale(self, last_data_date: Optional[date], as_of: date) -> bool:
        """Check if data is stale based on frequency and grace period.

        Args:
            last_data_date: Latest date in the dataset
            as_of: Reference date (typically today)

        Returns:
            True if data is stale
        """
        if last_data_date is None:
            return True

        expected = self.get_expected_date(as_of)
        threshold = expected - timedelta(days=self.grace_period_days)
        return last_data_date < threshold

    def _get_previous_business_day(self, d: date) -> date:
        """Get the previous business day (Mon-Fri).

        Args:
            d: Reference date

        Returns:
            Previous business day
        """
        result = d - timedelta(days=1)
        while result.weekday() >= 5:  # Saturday=5, Sunday=6
            result -= timedelta(days=1)
        return result


@dataclass
class FreshnessReport:
    """Report on freshness status of a resource and its upstreams."""

    resource_id: UUID
    status: DatasetStatus
    last_data_date: Optional[date] = None
    expected_date: Optional[date] = None
    all_ready: bool = False
    blocking_resources: list[UUID] = field(default_factory=list)
    status_map: dict[UUID, DatasetStatus] = field(default_factory=dict)


class FreshnessChecker:
    """Calculates staleness status for resources.

    The FreshnessChecker determines if a dataset is fresh, stale, or in error
    based on its UpdateFrequency configuration and the last pipeline run status.

    It also supports composite freshness checks for datasets with upstream
    dependencies - a dataset can only be "ready" if all its upstreams are ready.

    Example usage:
        checker = FreshnessChecker(status_store)

        # Check single dataset
        status = await checker.calculate_staleness(
            session, dataset_id, as_of=date.today()
        )

        # Check with upstream dependencies
        status = await checker.check_composite_freshness(session, dataset_id)
    """

    def __init__(self, status_store: "StatusStore") -> None:
        """Initialize FreshnessChecker.

        Args:
            status_store: StatusStore for loading execution metadata
        """
        self._status_store = status_store

    async def calculate_staleness(
        self,
        session: "AsyncSession",
        resource_id: UUID,
        *,
        as_of: Optional[date] = None,
        frequency: Optional[UpdateFrequency] = None,
    ) -> DatasetStatus:
        """Determine if a resource is fresh, stale, or error.

        Args:
            session: Database session
            resource_id: Dataset resource ID
            as_of: Reference date (defaults to today)
            frequency: Update frequency config (if not provided, loads from resource)

        Returns:
            DatasetStatus enum value
        """
        as_of = as_of or date.today()

        # Get status from status store
        status_record = await self._status_store.get_status(resource_id)

        if status_record is None:
            return DatasetStatus.NOT_INITIALIZED

        # Check for error state
        if status_record.last_pipeline_status == "error":
            return DatasetStatus.ERROR

        # Check if data exists
        if status_record.last_data_date is None:
            return DatasetStatus.NOT_INITIALIZED

        # Load frequency from resource if not provided
        if frequency is None:
            frequency = await self._load_frequency(session, resource_id)

        # Check for source delay
        if status_record.source_delay_detected:
            return DatasetStatus.STALE_SOURCE_DELAYED

        # Check staleness
        if frequency.is_stale(status_record.last_data_date, as_of):
            return DatasetStatus.STALE

        return DatasetStatus.READY

    async def check_composite_freshness(
        self,
        session: "AsyncSession",
        resource_id: UUID,
        *,
        upstream_ids: Optional[list[UUID]] = None,
    ) -> FreshnessReport:
        """Aggregate freshness for composite datasets.

        Checks freshness of this resource AND all its upstream dependencies.

        Rules:
        - If ANY upstream is NOT_INITIALIZED -> NOT_INITIALIZED
        - If ANY upstream is ERROR -> ERROR
        - If ANY upstream is STALE -> STALE
        - Only if ALL upstreams are READY -> check own freshness

        Args:
            session: Database session
            resource_id: Dataset resource ID
            upstream_ids: Optional list of upstream IDs (if not provided, looks up)

        Returns:
            FreshnessReport with aggregate status
        """
        status_map: dict[UUID, DatasetStatus] = {}
        blocking_resources: list[UUID] = []

        # Get upstream IDs if not provided
        if upstream_ids is None:
            upstream_ids = await self._get_upstream_ids(session, resource_id)

        # Check each upstream
        for upstream_id in upstream_ids:
            upstream_status = await self.calculate_staleness(session, upstream_id)
            status_map[upstream_id] = upstream_status

            if upstream_status in (
                DatasetStatus.NOT_INITIALIZED,
                DatasetStatus.ERROR,
                DatasetStatus.STALE,
                DatasetStatus.STALE_SOURCE_DELAYED,
            ):
                blocking_resources.append(upstream_id)

        # Determine aggregate status
        if blocking_resources:
            # Prioritize error states
            for uid in blocking_resources:
                if status_map[uid] == DatasetStatus.ERROR:
                    return FreshnessReport(
                        resource_id=resource_id,
                        status=DatasetStatus.ERROR,
                        all_ready=False,
                        blocking_resources=blocking_resources,
                        status_map=status_map,
                    )
                if status_map[uid] == DatasetStatus.NOT_INITIALIZED:
                    return FreshnessReport(
                        resource_id=resource_id,
                        status=DatasetStatus.NOT_INITIALIZED,
                        all_ready=False,
                        blocking_resources=blocking_resources,
                        status_map=status_map,
                    )

            # Otherwise STALE
            return FreshnessReport(
                resource_id=resource_id,
                status=DatasetStatus.STALE,
                all_ready=False,
                blocking_resources=blocking_resources,
                status_map=status_map,
            )

        # All upstreams ready - check own freshness
        own_status = await self.calculate_staleness(session, resource_id)
        status_record = await self._status_store.get_status(resource_id)

        frequency = await self._load_frequency(session, resource_id)
        expected_date = frequency.get_expected_date(date.today()) if frequency else None

        return FreshnessReport(
            resource_id=resource_id,
            status=own_status,
            last_data_date=status_record.last_data_date if status_record else None,
            expected_date=expected_date,
            all_ready=own_status == DatasetStatus.READY,
            blocking_resources=[],
            status_map={resource_id: own_status, **status_map},
        )

    async def detect_source_delay(
        self,
        session: "AsyncSession",
        resource_id: UUID,
    ) -> bool:
        """Check if a source has delayed data delivery.

        This is used for external data sources (e.g., Bloomberg, FRED)
        where the data may not be available at the expected time.

        Args:
            session: Database session
            resource_id: Dataset resource ID

        Returns:
            True if source delay is detected
        """
        status_record = await self._status_store.get_status(resource_id)
        if status_record is None:
            return False

        return status_record.source_delay_detected

    async def _load_frequency(
        self,
        session: "AsyncSession",
        resource_id: UUID,
    ) -> UpdateFrequency:
        """Load UpdateFrequency from resource config.

        Args:
            session: Database session
            resource_id: Dataset resource ID

        Returns:
            UpdateFrequency (defaults to daily if not configured)
        """
        from libs.db.models.quant import DatasetInstance

        dataset = await session.get(DatasetInstance, resource_id)
        if dataset is None:
            return UpdateFrequency()

        config = getattr(dataset, "config_json", None) or {}
        freq_config = config.get("update_frequency", {})

        return UpdateFrequency(
            frequency=freq_config.get("frequency", "daily"),
            grace_period_days=freq_config.get("grace_period_days", 0),
            business_days_only=freq_config.get("business_days_only", False),
            day_of_week=freq_config.get("day_of_week"),
            day_of_month=freq_config.get("day_of_month"),
        )

    async def _get_upstream_ids(
        self,
        session: "AsyncSession",
        resource_id: UUID,
    ) -> list[UUID]:
        """Get upstream dependency IDs from lineage table.

        Args:
            session: Database session
            resource_id: Dataset resource ID

        Returns:
            List of upstream resource IDs
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        stmt = select(DatasetLineage.upstream_resource_id).where(
            DatasetLineage.downstream_resource_id == resource_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
