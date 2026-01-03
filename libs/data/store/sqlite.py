"""SQLite Store Implementation.

Database-backed storage for relational data.
Used for reference data, external databases, and shared tables.

Adapted from optaic-v0/data/store/sqlite.py.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.data.registry import register_store

if TYPE_CHECKING:
    import pandas as pd

from libs.data.store.base import BaseStore


@register_store("SQLiteStore")
class SQLiteStore(BaseStore):
    """SQLite-backed data store.

    Used for:
    - Reading from external SQLite databases
    - Shared reference data tables
    - Legacy data sources

    Config Options:
    - db_path: Path to SQLite database file
    - table_name: Table name to read from
    - primary_key: Primary key column (default: "date")
    - writable: Allow write operations (default: False)

    Note: By default, SQLite stores are read-only to protect
    shared database integrity.
    """

    supports_deletion = False
    supports_append = False  # Read-only by default
    supports_partitioning = False

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        data_dir: Path | str,
    ) -> None:
        super().__init__(resource_id, config, data_dir)
        self._db_path = self._resolve_db_path()
        self._table_name = config.get("table_name")

        if not self._table_name:
            raise ValueError("SQLiteStore requires 'table_name' in config")

    def _resolve_db_path(self) -> Path:
        """Resolve the database file path."""
        db_path = self.config.get("db_path")
        if db_path:
            return Path(db_path)
        # Default: use data_dir/sqlite/<resource_id>.db
        return self.data_dir / "sqlite" / f"{self.resource_id}.db"

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(str(self._db_path))

    def read(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Read data from SQLite table with optional filtering."""
        import pandas as pd

        if not self.exists():
            return pd.DataFrame()

        # Build column selection
        col_clause = ", ".join(columns) if columns else "*"
        query = f"SELECT {col_clause} FROM {self._table_name}"  # noqa: S608

        # Build WHERE clause for date filtering
        primary_key = self.config.get("primary_key", "date")
        where_parts = []
        params: dict[str, Any] = {}

        if start_date:
            where_parts.append(f"{primary_key} >= :start_date")
            params["start_date"] = str(start_date)
        if end_date:
            where_parts.append(f"{primary_key} <= :end_date")
            params["end_date"] = str(end_date)

        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)

        query += f" ORDER BY {primary_key}"

        with closing(self._get_conn()) as conn:
            try:
                df = pd.read_sql_query(
                    query,
                    conn,
                    params=params,
                    parse_dates=[primary_key]
                    if "date" in primary_key.lower()
                    else None,
                )
            except Exception:
                # Fallback without date parsing
                df = pd.read_sql_query(query, conn, params=params)

        return df

    def write(
        self,
        data: "pd.DataFrame",
        mode: str = "append",
        **kwargs: Any,
    ) -> int:
        """Write data to SQLite table (if writable)."""

        if not self.config.get("writable", False):
            raise NotImplementedError(
                "SQLiteStore is read-only by default. Set 'writable: true' in config."
            )

        if data.empty:
            return 0

        # Ensure parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Map mode to pandas if_exists
        if_exists = "append" if mode == "append" else "replace"

        with closing(self._get_conn()) as conn:
            data.to_sql(
                self._table_name,
                conn,
                if_exists=if_exists,
                index=False,
            )

        return len(data)

    def exists(self) -> bool:
        """Check if database file and table exist."""
        if not self._db_path.exists():
            return False

        query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?;"
        try:
            with closing(self._get_conn()) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (self._table_name,))
                return cursor.fetchone() is not None
        except Exception:
            return False

    def get_columns(self) -> list[str]:
        """Get column names from table schema."""
        if not self.exists():
            return []

        query = f"PRAGMA table_info({self._table_name})"  # noqa: S608
        try:
            with closing(self._get_conn()) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [row[1] for row in cursor.fetchall()]
        except Exception:
            return []

    def get_date_range(self) -> tuple[date | None, date | None]:
        """Get min/max dates from the table."""
        if not self.exists():
            return (None, None)

        primary_key = self.config.get("primary_key", "date")
        query = f"SELECT MIN({primary_key}), MAX({primary_key}) FROM {self._table_name}"  # noqa: S608

        try:
            with closing(self._get_conn()) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                row = cursor.fetchone()
                if row and row[0] and row[1]:
                    from datetime import datetime

                    min_date = datetime.strptime(row[0][:10], "%Y-%m-%d").date()
                    max_date = datetime.strptime(row[1][:10], "%Y-%m-%d").date()
                    return (min_date, max_date)
        except Exception:
            pass

        return (None, None)

    def get_row_count(self) -> int:
        """Get total row count."""
        if not self.exists():
            return 0

        query = f"SELECT COUNT(*) FROM {self._table_name}"  # noqa: S608
        try:
            with closing(self._get_conn()) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def execute_query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> "pd.DataFrame":
        """Execute a raw SQL query and return a DataFrame."""
        import pandas as pd

        with closing(self._get_conn()) as conn:
            return pd.read_sql(query, conn, params=params)

    def get_storage_path(self) -> Path | None:
        """Get the database file path."""
        return self._db_path
