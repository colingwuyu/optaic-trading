"""Data Store Implementations.

Storage backends for dataset data. Each store implements the BaseStore interface
and is registered with STORE_FACTORY.

Available Stores:
- ParquetStore: File-based columnar storage (recommended for time series)
- SQLiteStore: SQLite database storage (for relational data)
- VirtualStore: No physical storage, delegates to source datasets
- FlatFileStore: CSV, Excel, Parquet flat files
- ConfigStore: YAML configuration files (read-only)

Usage in Definitions:
StoreDef resources reference stores by their factory key (e.g., "ParquetStore").
When a DatasetInstance is created, the system instantiates the store using
STORE_FACTORY.build(code_ref, **config).
"""

from libs.data.store.base import BaseStore as BaseStore

# Import to register stores
from libs.data.store import config as _config  # noqa: F401
from libs.data.store import flatfile as _flatfile  # noqa: F401
from libs.data.store import parquet as _parquet  # noqa: F401
from libs.data.store import sqlite as _sqlite  # noqa: F401
from libs.data.store import virtual as _virtual  # noqa: F401
