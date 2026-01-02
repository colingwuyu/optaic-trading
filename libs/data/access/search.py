"""Search Accessor Implementation.

Accessor for searching column names (tickers) in a dataset using regex patterns.
Ported from optaic-v0/dev_tools/src/data/access/search.py.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict, Field

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd


class UniverseSearchRequest(BaseRequest):
    """Request model for UniverseSearchAccessor."""

    pattern: str = Field(
        default="",
        description="Regex or substring pattern to search for.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pattern": "SPX",
                },
                {
                    "pattern": ".*Index$",
                }
            ]
        }
    )


@register_accessor("UniverseSearchAccessor")
class UniverseSearchAccessor(BaseAccessor):
    """Accessor for searching column names (tickers) in a dataset.

    Searches available columns using regex or substring matching.
    Useful for discovering available tickers/fields in a dataset.
    """

    def get_request_model(self) -> type[UniverseSearchRequest]:
        """Return the request model."""
        return UniverseSearchRequest

    def get_output_columns(self) -> list[str]:
        """Return output column names."""
        return ["Ticker"]

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        pattern: str | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Search for column names matching the pattern.

        Args:
            start_date: Not used (columns don't vary by date)
            end_date: Not used (columns don't vary by date)
            pattern: Regex or substring pattern to search
            **kwargs: Additional arguments

        Returns:
            DataFrame with matching column names in 'Ticker' column
        """
        import pandas as pd

        # Get all columns
        all_cols = self._get_all_columns()

        # Remove common meta columns
        meta_cols = {"date", "Date", "DATE", "knowledge_date", "release_date", "index"}
        all_cols = [c for c in all_cols if c not in meta_cols]

        # Filter by pattern
        matches = []
        if pattern:
            try:
                matcher = re.compile(pattern, re.IGNORECASE)
                matches = [c for c in all_cols if matcher.search(c)]
            except re.error:
                # Fallback to simple substring match if regex is invalid
                matches = [c for c in all_cols if pattern.lower() in c.lower()]
        else:
            matches = all_cols

        return pd.DataFrame(matches, columns=["Ticker"])

    def _get_all_columns(self) -> list[str]:
        """Get all column names from the store."""
        if self.store is None:
            return []

        try:
            # Try optimized column retrieval
            if hasattr(self.store, "get_columns"):
                return self.store.get_columns()

            # Try SQL query for SQLite stores
            if hasattr(self.store, "execute_query"):
                table_name = self.config.get("table_name")
                if table_name:
                    query = f"SELECT * FROM {table_name} LIMIT 0"
                    df = self.store.execute_query(query)
                    return df.columns.tolist()

            # Fallback: read and get columns
            df = self.store.read()
            if df is not None and hasattr(df, "columns"):
                return list(df.columns)

        except Exception:
            pass

        return []
