"""Economics Accessor Implementation.

Handles macroeconomic data with vintage/revision support.
Ported from optaic-v0/data/access/economics.py.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict, Field

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd


class RevisionType(StrEnum):
    """Revision selection strategy for vintage data."""

    INITIAL = "initial"  # First release
    LATEST = "latest"  # Most recent known revision
    ALL = "all"  # All revisions


class DateType(StrEnum):
    """Date filter type for vintage data."""

    OBSERVATION = "observation"  # The date the data point refers to (e.g., GDP for Q1)
    RELEASE = "release"  # The date we are looking at the data (As-Of)


class EconomicsRequest(BaseRequest):
    """Request model for EconomicsAccessor.

    Note: Uses `as_of_date` from BaseRequest for point-in-time retrieval.
    """

    revision: RevisionType = Field(
        default=RevisionType.LATEST,
        description="Revision strategy: 'initial', 'latest', or 'all'.",
    )
    date_type: DateType = Field(
        default=DateType.OBSERVATION,
        description="Date filter applies to 'observation' or 'release' date.",
    )
    use_multiindex: bool = Field(
        default=False,
        description="Return MultiIndex (obs_date, release_date) to preserve PIT metadata.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2000-01-01",
                    "end_date": "2024-12-31",
                    "as_of_date": "2024-01-01",
                    "revision": "latest",
                    "date_type": "observation",
                    "use_multiindex": False,
                }
            ]
        }
    )


@register_accessor("EconomicsAccessor")
class EconomicsAccessor(BaseAccessor):
    """Accessor for macroeconomic data with vintage/revision support.

    Handles point-in-time (PIT) retrieval of economic indicators
    like GDP, CPI, etc. that have multiple revisions.

    Config Options:
    - observation_date_col: Column for observation date (default: from index)
    - release_date_col: Column for release date (default: "release_date")
    - value_col: Column for value (default: "value")

    PIT Semantics:
    - as_of_date: What date are we "looking from"?
    - Only data released on or before as_of_date is visible
    - revision="latest" returns the most recent known value as of as_of_date
    - revision="initial" returns the first release for each observation
    - revision="all" returns all revisions
    """

    def get_request_model(self) -> type[EconomicsRequest]:
        """Return the request model."""
        return EconomicsRequest

    def get_output_columns(self) -> list[str]:
        """Return expected output columns."""
        try:
            columns = super().get_output_columns()
            if columns:
                return columns
        except Exception:
            pass

        # Default economics columns
        return ["value", "release_date"]

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        revision: str | RevisionType = RevisionType.LATEST,
        date_type: str | DateType = DateType.OBSERVATION,
        use_multiindex: bool = False,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Retrieve economic data with vintage support.

        Args:
            start_date: Start date filter (on obs_date or release_date per date_type)
            end_date: End date filter
            as_of_date: Point-in-time date - only data released by this date
            revision: 'initial', 'latest', or 'all' revisions
            date_type: Filter by 'observation' or 'release' date
            use_multiindex: If True, return MultiIndex (obs_date, release_date)
            **kwargs: Additional arguments

        Returns:
            DataFrame with vintage-aware data
        """
        import pandas as pd

        retrieval_dt = as_of_date

        # Load full history from store
        df = self.store.read()

        if df is None or df.empty:
            return pd.DataFrame()

        # Get column names from config
        release_col = self.config.get("release_date_col", "release_date")

        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Check for release_date column
        if release_col in df.columns:
            df[release_col] = pd.to_datetime(df[release_col])
        else:
            # No vintage data - return as simple time series
            if start_date:
                df = df[df.index >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df.index <= pd.Timestamp(end_date)]
            return df

        # Parse dates
        retrieval_ts = pd.Timestamp(retrieval_dt) if retrieval_dt else pd.Timestamp.now()
        start_ts = pd.Timestamp(start_date) if start_date else None
        end_ts = pd.Timestamp(end_date) if end_date else None

        revision_str = str(revision).lower()
        date_type_str = str(date_type).lower()

        # 1. Filter by Retrieval Date (Point-In-Time)
        # Only show data that was released on or before retrieval_dt
        df_pit = df[df[release_col] <= retrieval_ts].copy()

        if df_pit.empty:
            return pd.DataFrame()

        # 2. Apply Date Filters (Start/End)
        if date_type_str == "release":
            # Filter by Release Date
            if start_ts:
                df_pit = df_pit[df_pit[release_col] >= start_ts]
            if end_ts:
                df_pit = df_pit[df_pit[release_col] <= end_ts]
        else:
            # Filter by Observation Date (Index)
            if start_ts:
                df_pit = df_pit[df_pit.index >= start_ts]
            if end_ts:
                df_pit = df_pit[df_pit.index <= end_ts]

        # 3. Handle Revisions
        # Data might have multiple rows for same index (revisions)
        if df_pit.index.name is None:
            df_pit.index.name = "obs_date"
        idx_name = df_pit.index.name

        # Sort by observation date and release date
        df_pit = df_pit.reset_index()
        df_pit = df_pit.sort_values([idx_name, release_col], ascending=[True, True])
        df_pit = df_pit.set_index(idx_name)

        if revision_str == "all":
            if use_multiindex:
                df_pit = df_pit.reset_index()
                df_pit = df_pit.set_index([idx_name, release_col])
            return df_pit

        elif revision_str == "initial":
            # First release for each observation date
            result = df_pit.groupby(level=0).first()
            if use_multiindex and release_col in result.columns:
                result = result.reset_index()
                result = result.set_index([idx_name, release_col])
            return result

        elif revision_str == "latest":
            # Latest release known as of as_of_date
            result = df_pit.groupby(level=0).last()
            if use_multiindex and release_col in result.columns:
                result = result.reset_index()
                result = result.set_index([idx_name, release_col])
            return result

        # Fallback
        if use_multiindex:
            df_pit = df_pit.reset_index()
            df_pit = df_pit.set_index([idx_name, release_col])
        return df_pit
