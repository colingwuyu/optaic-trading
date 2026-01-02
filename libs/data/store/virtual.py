"""Virtual Store Implementation.

In-memory storage with no physical persistence.
Used for computed/derived datasets and temporary caching.

Adapted from optaic-v0/data/store/virtual.py.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.data.registry import register_store
from libs.data.store.base import BaseStore

if TYPE_CHECKING:
    import pandas as pd


@register_store("VirtualStore")
class VirtualStore(BaseStore):
    """In-memory data store with no physical persistence.

    Used for:
    - Computed/derived datasets (expression results)
    - Temporary caching during preview
    - Datasets that don't need persistence

    Config Options:
    - primary_key: Column used for date filtering (default: "date")
    - cache_ttl_seconds: How long to keep data in memory (default: 3600)

    Note: Data is lost when the process restarts.
    """

    supports_deletion = True
    supports_append = True
    supports_partitioning = False

    # Class-level cache for virtual stores (shared across instances)
    _cache: dict[str, tuple["pd.DataFrame", float]] = {}

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        data_dir: Path | str,
    ) -> None:
        super().__init__(resource_id, config, data_dir)
        self._cache_ttl = config.get("cache_ttl_seconds", 3600)

    def _get_cached_data(self) -> "pd.DataFrame | None":
        """Get data from cache if valid."""

        if self.resource_id not in self._cache:
            return None

        data, timestamp = self._cache[self.resource_id]
        if time.time() - timestamp > self._cache_ttl:
            # Cache expired
            del self._cache[self.resource_id]
            return None

        return data

    def read(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Read data from memory cache with optional filtering."""
        import pandas as pd

        data = self._get_cached_data()
        if data is None:
            return pd.DataFrame()

        df = data.copy()

        # Apply column selection
        if columns:
            available = [c for c in columns if c in df.columns]
            df = df[available]

        # Apply date filtering
        primary_key = self.config.get("primary_key", "date")
        if primary_key in df.columns and (start_date or end_date):
            try:
                df[primary_key] = pd.to_datetime(df[primary_key])
                if start_date:
                    df = df[df[primary_key] >= pd.Timestamp(start_date)]
                if end_date:
                    df = df[df[primary_key] <= pd.Timestamp(end_date)]
            except Exception:
                pass  # Skip filtering if date conversion fails

        return df

    def write(
        self,
        data: "pd.DataFrame",
        mode: str = "append",
        **kwargs: Any,
    ) -> int:
        """Write data to memory cache."""
        import pandas as pd

        if data.empty:
            return 0

        if mode == "append" and self.resource_id in self._cache:
            existing, _ = self._cache[self.resource_id]
            data = pd.concat([existing, data], ignore_index=True)

        self._cache[self.resource_id] = (data.copy(), time.time())
        return len(data)

    def exists(self) -> bool:
        """Check if data exists in cache."""
        return self._get_cached_data() is not None

    def get_columns(self) -> list[str]:
        """Get column names from cached data."""
        data = self._get_cached_data()
        if data is not None and not data.empty:
            return list(data.columns)
        return []

    def get_date_range(self) -> tuple[date | None, date | None]:
        """Get min/max dates from cached data."""
        import pandas as pd

        data = self._get_cached_data()
        if data is None or data.empty:
            return (None, None)

        primary_key = self.config.get("primary_key", "date")
        if primary_key not in data.columns:
            return (None, None)

        try:
            dates = pd.to_datetime(data[primary_key])
            return (dates.min().date(), dates.max().date())
        except Exception:
            return (None, None)

    def get_row_count(self) -> int:
        """Get row count from cached data."""
        data = self._get_cached_data()
        return len(data) if data is not None else 0

    def clear(self) -> None:
        """Clear cached data."""
        if self.resource_id in self._cache:
            del self._cache[self.resource_id]

    def delete(self) -> None:
        """Delete cached data."""
        self.clear()

    def get_last_update_time(self) -> float | None:
        """Get timestamp of last write."""
        if self.resource_id in self._cache:
            _, timestamp = self._cache[self.resource_id]
            return timestamp
        return None

    def get_storage_path(self) -> Path | None:
        """Virtual stores have no physical path."""
        return None
