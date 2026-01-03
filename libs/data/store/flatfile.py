"""Flat File Store Implementation.

Reads from CSV, Excel, and Parquet flat files.
Ported from optaic-v0/data/store/flatfile.py.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.data.registry import register_store
from libs.data.store.base import BaseStore

if TYPE_CHECKING:
    import pandas as pd


@register_store("FlatFileStore")
class FlatFileStore(BaseStore):
    """Flat file store for CSV, Excel, and Parquet files.

    Reads files from the data directory based on config.

    Config Options:
    - file_path: Path to file (absolute or relative to data_dir)
    - file_name: Alternative to file_path (relative to data_dir)
    - date_column: Column to use for date filtering
    - columns: List of columns to load
    - read_kwargs: Dict of kwargs to pass to pandas read function
    """

    def _resolve_path(self) -> Path | None:
        """Resolve the file path from config."""
        # Try file_path first (can be absolute or relative)
        file_path = self.config.get("file_path")
        if file_path:
            path = Path(file_path)
            if path.is_absolute() and path.exists():
                return path
            # Try relative to data_dir
            rel_path = self.data_dir / path
            if rel_path.exists():
                return rel_path
            # Try as absolute even if it didn't exist (for error messages)
            if path.is_absolute():
                return path

        # Fall back to file_name (always relative to data_dir)
        file_name = self.config.get("file_name")
        if file_name:
            path = self.data_dir / file_name
            if path.exists():
                return path
            # Try absolute path
            abs_path = Path(file_name)
            if abs_path.exists():
                return abs_path

        return None

    def read(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Read data from flat file (CSV, Excel, Parquet).

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
            columns: Optional column filter
            **kwargs: Additional kwargs for pandas reader

        Returns:
            DataFrame with file contents
        """
        import pandas as pd

        path = self._resolve_path()
        if path is None or not path.exists():
            return pd.DataFrame()

        # Get read kwargs from config
        read_kwargs = self.config.get("read_kwargs", {}).copy()
        read_kwargs.update(kwargs)

        # Read based on file type
        suffix = path.suffix.lower()

        if suffix == ".csv":
            df = pd.read_csv(path, **read_kwargs)
        elif suffix in [".xlsx", ".xlsm", ".xls"]:
            df = pd.read_excel(path, **read_kwargs)
        elif suffix == ".parquet":
            df = pd.read_parquet(path, **read_kwargs)
        else:
            raise ValueError(f"Unsupported flat file type: {suffix}")

        # Apply date filtering if possible
        date_column = self.config.get("date_column") or self.config.get(
            "primary_key", "date"
        )
        if date_column in df.columns:
            df[date_column] = pd.to_datetime(df[date_column])
            df = df.set_index(date_column)
            if start_date or end_date:
                if start_date:
                    df = df[df.index >= pd.Timestamp(start_date)]
                if end_date:
                    df = df[df.index <= pd.Timestamp(end_date)]

        # Apply column filter
        if columns:
            available = [c for c in columns if c in df.columns]
            if available:
                df = df[available]

        return df

    def write(
        self,
        data: "pd.DataFrame",
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> int:
        """Write data to flat file.

        Args:
            data: DataFrame to write
            mode: Write mode (only 'overwrite' supported for flat files)
            **kwargs: Additional kwargs for pandas writer

        Returns:
            Number of rows written
        """
        file_path_config = self.config.get("file_path") or self.config.get("file_name")
        if not file_path_config:
            raise ValueError(
                "FlatFileStore requires 'file_path' or 'file_name' in config"
            )

        # Handle absolute vs relative paths
        file_path = Path(file_path_config)
        if file_path.is_absolute():
            path = file_path
        else:
            path = self.data_dir / file_path

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        suffix = path.suffix.lower()

        if suffix == ".csv":
            data.to_csv(path, index=False, **kwargs)
        elif suffix == ".parquet":
            data.to_parquet(path, index=False, **kwargs)
        elif suffix in [".xlsx", ".xlsm"]:
            data.to_excel(path, index=False, **kwargs)
        else:
            raise ValueError(f"Unsupported write file type: {suffix}")

        return len(data)

    def exists(self) -> bool:
        """Check if flat file exists."""
        path = self._resolve_path()
        return path is not None and path.exists()

    def get_columns(self) -> list[str]:
        """Get column names efficiently."""
        import pandas as pd

        path = self._resolve_path()
        if path is None or not path.exists():
            return []

        suffix = path.suffix.lower()

        try:
            if suffix == ".csv":
                df = pd.read_csv(path, nrows=0)
                return list(df.columns)
            elif suffix in [".xlsx", ".xlsm", ".xls"]:
                df = pd.read_excel(path, nrows=0)
                return list(df.columns)
            elif suffix == ".parquet":
                import pyarrow.parquet as pq

                schema = pq.read_schema(path)
                return schema.names
        except Exception:
            pass

        return []

    def get_row_count(self) -> int:
        """Get row count (requires reading file)."""
        path = self._resolve_path()
        if path is None or not path.exists():
            return 0

        suffix = path.suffix.lower()

        try:
            if suffix == ".csv":
                # Count lines without loading full file
                with open(path) as f:
                    return sum(1 for _ in f) - 1  # Subtract header
            elif suffix == ".parquet":
                import pyarrow.parquet as pq

                return pq.read_metadata(path).num_rows
        except Exception:
            pass

        # Fallback: read and count
        df = self.read()
        return len(df)

    def get_storage_path(self) -> Path | None:
        """Get the file path."""
        return self._resolve_path()

    def copy_to(self, destination: str) -> None:
        """Copy the file to a new location."""
        import shutil

        source_path = self._resolve_path()
        if source_path is None or not source_path.exists():
            raise FileNotFoundError("Source file not found")

        dest_path = Path(destination)
        if dest_path.exists():
            raise FileExistsError(f"Destination already exists: {dest_path}")

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)

    def delete(self) -> None:
        """Delete the flat file."""
        path = self._resolve_path()
        if path and path.exists():
            path.unlink()

    def clear(self) -> None:
        """Clear is same as delete for flat files."""
        self.delete()
