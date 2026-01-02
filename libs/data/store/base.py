"""Base Store Interface.

Defines the abstract interface for data storage backends.
Adapted from optaic-v0/data/store/base.py.

Key Difference from optaic-v0:
- Constructor takes resource_id instead of DatasetInfo
- Configuration comes from StoreDef + DatasetInstance
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


class BaseStore(ABC):
    """Abstract base class for data storage backends.

    A Store is responsible for the physical storage and retrieval of data.
    It does NOT handle business logic like PIT or access control - those
    are handled by Accessors and the Service layer respectively.

    Attributes:
        resource_id: The DatasetInstance resource ID this store belongs to
        config: Configuration dict from StoreDef + DatasetInstance
        data_dir: Base directory for data files (from platform config)
    """

    # Capability flags (override in subclasses)
    supports_deletion: bool = False
    supports_append: bool = True
    supports_partitioning: bool = False

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        data_dir: Path | str,
    ) -> None:
        """Initialize the store.

        Args:
            resource_id: The DatasetInstance resource ID
            config: Merged config from StoreDef + DatasetInstance
            data_dir: Base directory for data storage
        """
        self.resource_id = resource_id
        self.config = config
        self.data_dir = Path(data_dir)

    @abstractmethod
    def read(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Read data from the store.

        Args:
            start_date: Filter start date (inclusive)
            end_date: Filter end date (inclusive)
            columns: Columns to read (None = all)
            **kwargs: Store-specific arguments

        Returns:
            DataFrame with the requested data
        """

    @abstractmethod
    def write(
        self,
        data: "pd.DataFrame",
        mode: str = "append",
        **kwargs: Any,
    ) -> int:
        """Write data to the store.

        Args:
            data: DataFrame to write
            mode: Write mode ("append", "overwrite", "upsert")
            **kwargs: Store-specific arguments

        Returns:
            Number of rows written
        """

    @abstractmethod
    def exists(self) -> bool:
        """Check if the store has any data."""

    def get_columns(self) -> list[str]:
        """Get column names from the store.

        Returns:
            List of column names, empty if not available
        """
        return []

    def get_date_range(self) -> tuple[date | None, date | None]:
        """Get the date range of data in the store.

        Returns:
            Tuple of (min_date, max_date), or (None, None) if empty
        """
        return (None, None)

    def get_row_count(self) -> int:
        """Get the number of rows in the store.

        Returns:
            Row count, or 0 if not available
        """
        return 0

    def clear(self) -> None:
        """Clear all data from the store."""
        raise NotImplementedError(
            f"Clear not supported by {self.__class__.__name__}"
        )

    def delete(self) -> None:
        """Delete the physical store (file, table, etc.).

        Only available if supports_deletion is True.
        """
        raise NotImplementedError(
            f"Deletion not supported by {self.__class__.__name__}"
        )

    def get_storage_path(self) -> Path | None:
        """Get the physical storage path if applicable.

        Returns:
            Path to the storage location, or None for virtual stores
        """
        return None
