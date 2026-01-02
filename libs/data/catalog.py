"""Dataset Catalog Types.

Defines core types for dataset metadata. Adapted from optaic-v0/data/catalog.py
to work with the Resource model instead of standalone DatasetInfo objects.

Key Difference from optaic-v0:
- DatasetInfo was a standalone Pydantic model with ownership embedded
- In optaic-trading, ownership comes from the Resource table via tenant_id/owner_principal_id
- DatasetInstance extension table stores the dataset-specific metadata
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class BackendType(StrEnum):
    """Storage backend type for datasets."""

    SQLITE = "sqlite"
    PARQUET = "parquet"
    CONFIG = "config"
    FLATFILE = "flatfile"
    VIRTUAL = "virtual"
    CACHE = "cache"


class DatasetKind(StrEnum):
    """Classification of dataset temporal behavior."""

    TIME_SERIES = "time_series"  # Date-indexed data (prices, indicators)
    VINTAGE = "vintage"  # Point-in-time versioned (economic releases)
    STATIC = "static"  # Reference data (tickers, mappings)


class DatasetStatus(StrEnum):
    """Status of a dataset's data readiness and freshness."""

    NOT_INITIALIZED = "not_initialized"  # Store doesn't exist / no data
    READY = "ready"  # Data exists and is up-to-date
    STALE = "stale"  # Data exists but outdated
    STALE_SOURCE_DELAYED = "stale_source_delayed"  # Ran but source has no new data
    ERROR = "error"  # Pipeline error or data corruption


class UpdateFrequency(BaseModel):
    """Defines expected update schedule for a dataset.

    Used to calculate staleness based on the expected data availability date.
    """

    frequency: Literal[
        "daily",
        "weekly",
        "bi-weekly",
        "monthly",
        "quarterly",
        "annually",
        "irregular",
        "custom",
    ] = "daily"

    # Custom schedule parameters
    custom_days: int | None = None  # Every N days (for frequency="custom")
    day_of_week: int | None = None  # 0=Monday, 6=Sunday (for frequency="weekly")
    day_of_month: int | None = None  # 1-31 (for frequency="monthly")

    # Tolerance for source delays (e.g., FRED data may release with delay)
    grace_period_days: int = 0

    # Whether updates only occur on business days (Mon-Fri)
    business_days_only: bool = False

    def get_expected_date(self, today: date | None = None) -> date | None:
        """Calculate the expected latest data date based on frequency.

        Args:
            today: Reference date (defaults to date.today())

        Returns:
            The date by which data should be available, or None for irregular schedules.
        """
        if today is None:
            today = date.today()

        if self.frequency == "daily":
            if self.business_days_only:
                # For business day datasets, expect T-1 business day
                days_back = 1
                weekday = today.weekday()
                if weekday == 0:  # Monday
                    days_back = 3  # Expect Friday's data
                elif weekday == 6:  # Sunday
                    days_back = 2  # Expect Friday's data
                elif weekday == 5:  # Saturday
                    days_back = 1  # Expect Friday's data
                return today - timedelta(days=days_back)
            else:
                return today - timedelta(days=1)

        elif self.frequency == "weekly":
            target_dow = self.day_of_week if self.day_of_week is not None else 4
            days_since = (today.weekday() - target_dow) % 7
            if days_since == 0:
                days_since = 7
            return today - timedelta(days=days_since)

        elif self.frequency == "bi-weekly":
            return today - timedelta(days=14)

        elif self.frequency == "monthly":
            first_of_month = today.replace(day=1)
            return first_of_month - timedelta(days=1)

        elif self.frequency == "quarterly":
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            quarter_start = date(today.year, quarter_month, 1)
            return quarter_start - timedelta(days=1)

        elif self.frequency == "annually":
            return date(today.year - 1, 12, 31)

        elif self.frequency == "custom" and self.custom_days:
            return today - timedelta(days=self.custom_days)

        elif self.frequency == "irregular":
            return None

        return today - timedelta(days=1)


class DataPreviewRequest(BaseModel):
    """Request parameters for data preview.

    Replaces optaic-v0's BaseRequest with Resource-aware fields.
    """

    start_date: date = Field(
        default=date(1900, 1, 1),
        description="Start date filter (inclusive)",
    )
    end_date: date = Field(
        default=date(2099, 12, 31),
        description="End date filter (inclusive)",
    )
    as_of_date: date | None = Field(
        default=None,
        description="Point-in-time retrieval date for PIT correctness",
    )
    limit: int | None = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum rows to return",
    )
    columns: list[str] | None = Field(
        default=None,
        description="Columns to include (None = all)",
    )


class DataPreviewResponse(BaseModel):
    """Response from data preview operation."""

    resource_id: str
    resource_name: str
    row_count: int
    column_names: list[str]
    data: list[dict]  # Row-oriented data
    truncated: bool = False
    as_of_date: date | None = None
