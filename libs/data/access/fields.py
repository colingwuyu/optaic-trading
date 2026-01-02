"""Fields Accessor Implementation.

Accessor for dynamic field (column) selection from datasets.
Ported from optaic-v0/dev_tools/src/data/access/fields.py.
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


class FieldsRequest(BaseRequest):
    """Request model for FieldsAccessor."""

    fields: list[str] = Field(
        default_factory=list,
        description="List of fields (columns) to retrieve.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2023-01-01",
                    "end_date": "2023-12-31",
                    "fields": ["open", "close"],
                }
            ]
        }
    )


@register_accessor("FieldsAccessor")
class FieldsAccessor(BaseAccessor):
    """Accessor for field (column) selection from datasets.

    Provides dynamic field selection based on available columns in the
    underlying dataset. Supports case-insensitive field matching.
    """

    def get_request_model(self) -> type[FieldsRequest]:
        """Return the request model."""
        return FieldsRequest

    def get_output_columns(self) -> list[str]:
        """Return available columns from the store."""
        if self.store is None:
            return []

        try:
            if hasattr(self.store, "get_columns"):
                return self.store.get_columns()
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
        fields: list[str] | list[Enum] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Retrieve data with optional field filtering.

        Args:
            start_date: Start date filter
            end_date: End date filter
            fields: List of field names to select
            **kwargs: Additional arguments

        Returns:
            DataFrame with selected fields
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

        # No field filter - return all
        if not fields:
            return df

        # Clean Enum values if present
        clean_fields = []
        for f in fields:
            clean_fields.append(f.value if isinstance(f, Enum) else f)

        # Try exact match first
        if all(f in df.columns for f in clean_fields):
            return df[clean_fields]

        # Try case-insensitive match
        field_lower = [f.lower() for f in clean_fields]
        available_fields = []
        for col in df.columns:
            if col.lower() in field_lower:
                available_fields.append(col)

        if not available_fields:
            return pd.DataFrame(index=df.index)

        return df[available_fields]
