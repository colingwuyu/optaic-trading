"""Ticker Accessor Implementation.

Accessor for ticker-based data selection from datasets.
Ported from optaic-v0/dev_tools/src/data/access/ticker.py.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict, Field

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd


class TickerRequest(BaseRequest):
    """Request model for TickerAccessor."""

    tickers: list[str] = Field(
        default_factory=list,
        description="List of tickers (columns) to retrieve.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2023-01-01",
                    "end_date": "2023-12-31",
                    "tickers": ["SPX Index", "NDX Index"],
                }
            ]
        }
    )


@register_accessor("TickerAccessor")
class TickerAccessor(BaseAccessor):
    """Accessor for ticker-based data selection.

    Provides data retrieval filtered by ticker symbols. Supports
    both list and comma-separated string input for tickers.
    """

    def get_request_model(self) -> type[TickerRequest]:
        """Return the request model."""
        return TickerRequest

    def get_output_columns(self) -> list[str]:
        """Return available tickers from the store."""
        if self.store is None:
            return []

        try:
            if hasattr(self.store, "get_columns"):
                cols = self.store.get_columns()
                # Filter out common meta columns
                meta_cols = {"date", "Date", "DATE", "knowledge_date", "release_date"}
                return [c for c in cols if c not in meta_cols]

            # Fallback: read and get columns
            df = self.store.read()
            if df is not None and hasattr(df, "columns"):
                return list(df.columns)
        except Exception:
            pass

        return []

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        tickers: list[str] | str | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Retrieve data with optional ticker filtering.

        Args:
            start_date: Start date filter
            end_date: End date filter
            tickers: List of ticker names or comma-separated string
            **kwargs: Additional arguments

        Returns:
            DataFrame with selected tickers as columns
        """
        import pandas as pd

        if self.store is None:
            return pd.DataFrame()

        # Read data
        df = self.store.read(
            start_date=start_date,
            end_date=end_date,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        # No ticker filter - return all
        if not tickers:
            return df

        # Parse tickers
        clean_tickers = []
        if isinstance(tickers, str):
            clean_tickers = [t.strip() for t in tickers.split(",")]
        else:
            for t in tickers:
                clean_tickers.append(t.value if isinstance(t, Enum) else t)

        # Filter to existing columns only
        existing_cols = [c for c in clean_tickers if c in df.columns]
        if existing_cols:
            return df[existing_cols]
        else:
            return pd.DataFrame(index=df.index)
