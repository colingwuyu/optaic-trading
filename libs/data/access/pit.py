"""Point-in-Time (PIT) Accessor Implementation.

Handles vintage/versioned data with proper point-in-time semantics.
Essential for backtesting to avoid lookahead bias.

PIT correctness means: "What would we have known on date X?"
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import Field

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd


class PITRequest(BaseRequest):
    """Request model for PIT accessor with required as_of_date."""

    as_of_date: date = Field(
        ...,  # Required field
        description="Point-in-time date: what data was available on this date?",
    )


@register_accessor("PITAccessor")
class PITAccessor(BaseAccessor):
    """Point-in-Time accessor for vintage/versioned data.

    Handles data that has multiple versions per observation date,
    such as economic releases that get revised over time.

    Required columns in source data:
    - observation_date (or primary_key): The date the data refers to
    - knowledge_date: The date when this version became available

    Example: GDP for 2024-Q1
    - observation_date: 2024-03-31 (end of quarter)
    - knowledge_date: 2024-04-28 (advance estimate release)
    - knowledge_date: 2024-05-30 (second estimate)
    - knowledge_date: 2024-06-28 (third estimate)

    When querying with as_of_date=2024-05-15:
    - Returns the advance estimate (knowledge_date: 2024-04-28)
    - Does NOT return second estimate (not yet known)

    Config Options:
    - observation_date_col: Column for observation date (default: "date")
    - knowledge_date_col: Column for knowledge date (default: "knowledge_date")
    """

    def get_request_model(self) -> type[PITRequest]:
        """PIT accessor requires as_of_date."""
        return PITRequest

    def get(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Load data with point-in-time correctness.

        Args:
            start_date: Filter start date for observation dates
            end_date: Filter end date for observation dates
            as_of_date: Point-in-time date (what was known on this date)
            columns: Columns to include
            **kwargs: Additional store arguments

        Returns:
            DataFrame with the latest version of each observation
            that was known as of as_of_date

        Raises:
            ValueError: If as_of_date is not provided
        """
        import pandas as pd

        if as_of_date is None:
            raise ValueError("PITAccessor requires as_of_date parameter")

        # Get column names from config
        obs_col = self.config.get("observation_date_col", "date")
        knowledge_col = self.config.get("knowledge_date_col", "knowledge_date")

        # Read all data (we need knowledge_date for filtering)
        required_cols = None
        if columns:
            # Ensure we have the columns needed for PIT filtering
            required_cols = list(set(columns + [obs_col, knowledge_col]))

        df = self.store.read(
            start_date=start_date,
            end_date=end_date,
            columns=required_cols,
            **kwargs,
        )

        if df.empty:
            return df

        # Ensure knowledge_date column exists
        if knowledge_col not in df.columns:
            raise ValueError(
                f"PITAccessor requires '{knowledge_col}' column in data. "
                f"Available columns: {list(df.columns)}"
            )

        # Convert date columns
        df[knowledge_col] = pd.to_datetime(df[knowledge_col])
        if obs_col in df.columns:
            df[obs_col] = pd.to_datetime(df[obs_col])

        # Filter to versions known as of as_of_date
        df = df[df[knowledge_col] <= pd.Timestamp(as_of_date)]

        if df.empty:
            return df

        # For each observation date, keep only the latest known version
        # (the one with the maximum knowledge_date)
        if obs_col in df.columns:
            # Get index of max knowledge_date for each observation
            idx = df.groupby(obs_col)[knowledge_col].idxmax()
            df = df.loc[idx]

            # Sort by observation date
            df = df.sort_values(obs_col)

        # Remove knowledge_date from output if not in requested columns
        if columns and knowledge_col not in columns and knowledge_col in df.columns:
            df = df.drop(columns=[knowledge_col])

        return df

    def get_output_columns(self) -> list[str]:
        """Get output columns (excluding knowledge_date by default)."""
        all_cols = self.store.get_columns()
        knowledge_col = self.config.get("knowledge_date_col", "knowledge_date")

        # Exclude knowledge_date from default output
        return [c for c in all_cols if c != knowledge_col]

    def validate_request(self, request: PITRequest) -> None:
        """Validate PIT request."""
        super().validate_request(request)

        # Ensure as_of_date is not in the future (optional strictness)
        if request.as_of_date > date.today():
            # This is a warning, not an error - future dates may be valid for testing
            pass
