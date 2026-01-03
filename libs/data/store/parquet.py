"""Parquet Store Implementation.

File-based columnar storage using Apache Arrow/Parquet.
Recommended for time series data due to efficient date filtering.

Adapted from optaic-v0/data/store/parquet.py.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.data.registry import register_store

if TYPE_CHECKING:
    import pandas as pd

from libs.data.store.base import BaseStore


@register_store("ParquetStore")
class ParquetStore(BaseStore):
    """Parquet-based data store with partitioning support.

    Features:
    - Columnar storage with compression
    - Hive-style partitioning by date/year
    - Predicate pushdown for efficient filtering
    - Schema preservation via Arrow

    Config Options:
    - filename: Override default filename (resource_id)
    - primary_key: Column used for date filtering (default: "date")
    - partition_by_year: Enable year-based partitioning (default: True)
    """

    supports_deletion = True
    supports_append = True
    supports_partitioning = True

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        data_dir: Path | str,
    ) -> None:
        super().__init__(resource_id, config, data_dir)
        self._dataset_path = self._resolve_dataset_path()
        self._dataset_path.parent.mkdir(parents=True, exist_ok=True)

    def _resolve_dataset_path(self) -> Path:
        """Resolve the dataset storage path."""
        filename = self.config.get("filename", self.resource_id)
        return self.data_dir / "parquet" / filename

    def read(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Read data from Parquet store with optional filtering.

        Uses PyArrow dataset for efficient predicate pushdown.
        """
        import pandas as pd
        import pyarrow.dataset as ds

        if not self.exists():
            return pd.DataFrame()

        ds_obj = ds.dataset(
            self._dataset_path,
            format="parquet",
            partitioning="hive",
        )

        # Build filter expression
        filters = []
        primary_key = self.config.get("primary_key", "date")
        if primary_key in ds_obj.schema.names:
            if start_date:
                filters.append(ds.field(primary_key) >= pd.Timestamp(start_date))
            if end_date:
                filters.append(ds.field(primary_key) <= pd.Timestamp(end_date))

        # Read with optional column selection and filtering
        table = (
            ds_obj.to_table(
                columns=columns,
                filter=ds.field("_").is_valid()
                if not filters
                else filters[0]
                if len(filters) == 1
                else filters[0] & filters[1],
            )
            if filters
            else ds_obj.to_table(columns=columns)
        )

        df = table.to_pandas()

        # Sort by primary key if present
        if primary_key in df.columns:
            df = df.sort_values(primary_key)

        return df

    def write(
        self,
        data: "pd.DataFrame",
        mode: str = "append",
        **kwargs: Any,
    ) -> int:
        """Write data to Parquet store.

        Args:
            data: DataFrame to write
            mode: "append" or "overwrite"

        Returns:
            Number of rows written
        """
        import pandas as pd
        import pyarrow as pa
        import pyarrow.dataset as ds

        if data.empty:
            return 0

        # Handle overwrite mode
        if mode == "overwrite" and self._dataset_path.exists():
            shutil.rmtree(self._dataset_path)

        self._dataset_path.mkdir(parents=True, exist_ok=True)

        # Reset index if primary key is in index
        primary_key = self.config.get("primary_key", "date")
        if primary_key in data.index.names:
            df_to_write = data.reset_index()
        else:
            df_to_write = data.copy()

        # Set up partitioning
        partition_cols = []
        if self.config.get("partition_by_year", True):
            if primary_key in df_to_write.columns:
                try:
                    df_to_write[f"{primary_key}_year"] = pd.to_datetime(
                        df_to_write[primary_key]
                    ).dt.year
                    partition_cols.append(f"{primary_key}_year")
                except Exception:
                    pass  # Skip partitioning if date conversion fails

        # Write to Parquet
        table = pa.Table.from_pandas(df_to_write)
        ds.write_dataset(
            table,
            base_dir=self._dataset_path,
            format="parquet",
            partitioning=partition_cols if partition_cols else None,
            existing_data_behavior="overwrite_or_ignore",
        )

        return len(data)

    def exists(self) -> bool:
        """Check if dataset has any data files."""
        if not self._dataset_path.exists():
            return False
        return any(self._dataset_path.rglob("*.parquet"))

    def get_columns(self) -> list[str]:
        """Get column names from schema without reading data."""
        import pyarrow.dataset as ds

        if not self.exists():
            return []

        try:
            ds_obj = ds.dataset(
                self._dataset_path,
                format="parquet",
                partitioning="hive",
            )
            # Filter out partition columns (ending with _year)
            return [name for name in ds_obj.schema.names if not name.endswith("_year")]
        except Exception:
            return []

    def get_date_range(self) -> tuple[date | None, date | None]:
        """Get min/max dates from the dataset."""
        import pandas as pd

        if not self.exists():
            return (None, None)

        primary_key = self.config.get("primary_key", "date")
        df = self.read(columns=[primary_key])

        if df.empty or primary_key not in df.columns:
            return (None, None)

        try:
            dates = pd.to_datetime(df[primary_key])
            return (dates.min().date(), dates.max().date())
        except Exception:
            return (None, None)

    def get_row_count(self) -> int:
        """Get total row count."""
        import pyarrow.dataset as ds

        if not self.exists():
            return 0

        try:
            ds_obj = ds.dataset(
                self._dataset_path,
                format="parquet",
                partitioning="hive",
            )
            return ds_obj.count_rows()
        except Exception:
            return 0

    def clear(self) -> None:
        """Delete all data files but keep directory."""
        if self._dataset_path.exists():
            shutil.rmtree(self._dataset_path)
            self._dataset_path.mkdir(parents=True, exist_ok=True)

    def delete(self) -> None:
        """Delete the entire dataset directory."""
        if self._dataset_path.exists():
            shutil.rmtree(self._dataset_path)

    def get_storage_path(self) -> Path | None:
        """Get the storage path."""
        return self._dataset_path
