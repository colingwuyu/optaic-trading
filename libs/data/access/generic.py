"""Generic Accessor Implementations.

Universal accessors for SQL tables and generic data.
Ported from optaic-v0/data/access/generic.py.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import Field

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd


class SQLTableStaticRequest(BaseRequest):
    """Request model for SQLTableStaticAccessor."""

    columns: list[str] = Field(
        default_factory=list,
        description="Columns to retrieve.",
    )


@register_accessor("SQLTableStaticAccessor")
class SQLTableStaticAccessor(BaseAccessor):
    """Universal accessor for SQLite tables.

    Supports:
    - Full table retrieval
    - Date filtering (if date column exists)
    - Column selection

    Config Options:
    - date_column: Name of date column for filtering (default: "date")
    """

    def get_request_model(self) -> type[SQLTableStaticRequest]:
        """Return the request model."""
        return SQLTableStaticRequest

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Retrieve data from SQL table.

        Args:
            start_date: Filter start date
            end_date: Filter end date
            as_of_date: Point-in-time date
            columns: Columns to include
            **kwargs: Additional arguments

        Returns:
            DataFrame with filtered data
        """
        import pandas as pd

        # Load from store
        df = self.store.read(
            start_date=start_date,
            end_date=end_date,
            columns=columns,
            **kwargs,
        )

        if df.empty:
            return df

        # Column filtering
        if columns:
            available = [c for c in columns if c in df.columns]
            if available:
                df = df[available]

        # Date filtering
        if start_date or end_date:
            date_col = self.config.get("date_column", "date")

            # Check if index is date-like
            if isinstance(df.index, pd.DatetimeIndex):
                if start_date:
                    df = df[df.index >= pd.Timestamp(start_date)]
                if end_date:
                    df = df[df.index <= pd.Timestamp(end_date)]
            # Check for date column
            elif date_col in df.columns:
                try:
                    dates = pd.to_datetime(df[date_col])
                    mask = pd.Series(True, index=df.index)
                    if start_date:
                        mask &= dates >= pd.Timestamp(start_date)
                    if end_date:
                        mask &= dates <= pd.Timestamp(end_date)
                    df = df[mask.values]
                except Exception:
                    pass  # Date column not parsable

        return df


class GenericSQLRequest(BaseRequest):
    """Request model for GenericSQLAccessor."""

    query: str = Field(
        default="",
        description="SQL query to execute.",
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="Parameters for the SQL query.",
    )


@register_accessor("GenericSQLAccessor")
class GenericSQLAccessor(BaseAccessor):
    """Generic accessor for executing SQL queries.

    Allows running custom SQL queries against the backend.

    Config Options:
    - query: Default SQL query to execute
    """

    def get_request_model(self) -> type[GenericSQLRequest]:
        """Return the request model."""
        return GenericSQLRequest

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        query: str | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Execute SQL query and return results.

        Args:
            start_date: Filter start date (fallback if no query)
            end_date: Filter end date (fallback if no query)
            as_of_date: Point-in-time date
            query: SQL query to execute
            params: Query parameters
            **kwargs: Additional arguments

        Returns:
            DataFrame with query results
        """
        import pandas as pd

        # Get query from config or parameter
        sql = self.config.get("query") or query

        if sql:
            # Execute raw SQL if store supports it
            if hasattr(self.store, "execute_query"):
                return self.store.execute_query(sql, params=params)
            else:
                raise NotImplementedError(
                    f"Store {type(self.store).__name__} does not support raw SQL execution"
                )

        # Fallback to standard read
        df = self.store.read(
            start_date=start_date,
            end_date=end_date,
            **kwargs,
        )

        # Apply date filtering
        if start_date or end_date:
            date_col = self.config.get("date_column", "date")

            if isinstance(df.index, pd.DatetimeIndex):
                if start_date:
                    df = df[df.index >= pd.Timestamp(start_date)]
                if end_date:
                    df = df[df.index <= pd.Timestamp(end_date)]
            elif date_col in df.columns:
                try:
                    dates = pd.to_datetime(df[date_col])
                    mask = pd.Series(True, index=df.index)
                    if start_date:
                        mask &= dates >= pd.Timestamp(start_date)
                    if end_date:
                        mask &= dates <= pd.Timestamp(end_date)
                    df = df[mask.values]
                except Exception:
                    pass

        return df
