"""Simple Accessor Implementation.

Basic pass-through accessor with date filtering.
Recommended for most datasets that don't need PIT handling.

Adapted from optaic-v0/data/access/simple.py.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd


@register_accessor("SimpleAccessor")
@register_accessor("BaseAccessor")  # Alias for backwards compatibility
class SimpleAccessor(BaseAccessor):
    """Simple pass-through accessor with date filtering.

    Provides basic data access with date range filtering.
    Use for time series datasets that don't require point-in-time handling.

    Features:
    - Date range filtering (start_date, end_date)
    - Optional as_of_date cutoff (filters by index date)
    - Column selection
    """

    def get_request_model(self) -> type[BaseRequest]:
        """Use standard request model."""
        return BaseRequest

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Load data with optional date filtering.

        Args:
            start_date: Filter start date (inclusive)
            end_date: Filter end date (inclusive)
            as_of_date: Cutoff date for data availability
            columns: Columns to include
            **kwargs: Additional store arguments

        Returns:
            DataFrame with filtered data
        """
        import pandas as pd

        # Read from store with date filtering
        df = self.store.read(
            start_date=start_date,
            end_date=end_date,
            columns=columns,
            **kwargs,
        )

        if df.empty:
            return df

        # Apply as_of_date cutoff if provided
        # This filters to data that would have been available at as_of_date
        if as_of_date is not None:
            primary_key = self.config.get("primary_key", "date")
            if primary_key in df.columns:
                try:
                    df = df[pd.to_datetime(df[primary_key]) <= pd.Timestamp(as_of_date)]
                except Exception:
                    pass  # Skip if date conversion fails
            elif isinstance(df.index, pd.DatetimeIndex):
                df = df[df.index <= pd.Timestamp(as_of_date)]

        return df
