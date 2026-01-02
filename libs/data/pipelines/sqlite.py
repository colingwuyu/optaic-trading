"""SQLite Update Pipeline Implementation.

Pipeline for updating SQLite database files from production.
Ported from optaic-v0/dev_tools/src/pipelines/data/sqlite.py.
"""

from __future__ import annotations

import datetime
import gc
import pathlib
import shutil
import time
from typing import TYPE_CHECKING, Any

from libs.data.pipelines.base import DataPipeline
from libs.data.registry import register_pipeline

if TYPE_CHECKING:
    import pandas as pd


@register_pipeline("SQLiteUpdatePipeline")
class SQLiteUpdatePipeline(DataPipeline):
    """Pipeline to update SQLite database file from a source location.

    This pipeline handles file-level operations rather than data transformation.
    It backs up the existing file and copies a new version from the source.

    Config Options:
    - source_path: Path to the source SQLite file
    - target_path: Path to the target SQLite file (local)
    - max_retries: Maximum number of retry attempts (default: 3)
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize SQLiteUpdatePipeline.

        Args:
            resource_id: Pipeline resource ID
            config: Configuration containing 'source_path' and 'target_path'
            store: Optional store (not used for file operations)
            **kwargs: Additional config
        """
        super().__init__(resource_id, config, store, **kwargs)

        self.source_path = config.get("source_path")
        self.target_path = config.get("target_path")
        self.max_retries = config.get("max_retries", 3)

        if not self.source_path:
            raise ValueError("SQLiteUpdatePipeline requires 'source_path' in config")
        if not self.target_path:
            raise ValueError("SQLiteUpdatePipeline requires 'target_path' in config")

    def extract(self, **kwargs: Any) -> str:
        """Verify source file exists.

        Returns:
            Path to source file
        """
        source_path = pathlib.Path(self.source_path)

        if not source_path.exists():
            raise FileNotFoundError(f"Source database missing at {self.source_path}")

        return str(source_path)

    def transform(self, raw_data: Any, **kwargs: Any) -> "pd.DataFrame":
        """No transformation for file copy.

        Returns:
            Empty DataFrame (file operations don't produce data)
        """
        import pandas as pd

        return pd.DataFrame()

    def run(
        self,
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute file copy with retry logic.

        This overrides the base run() to perform file operations
        instead of data transformation.

        Args:
            mode: Write mode (ignored for file operations)
            **kwargs: Additional parameters

        Returns:
            Run statistics
        """
        # Force GC to close potential dangling handles
        gc.collect()

        source_path = pathlib.Path(self.source_path)
        target_path = pathlib.Path(self.target_path)

        if not source_path.exists():
            return {
                "status": "failed",
                "rows": 0,
                "start_date": None,
                "end_date": None,
                "error": f"Source file not found: {self.source_path}",
            }

        for attempt in range(self.max_retries):
            try:
                # 1. Rename existing to backup
                if target_path.exists():
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = f"{self.target_path}.{timestamp}.bak"
                    target_path.rename(backup_path)

                # 2. Copy new file
                shutil.copy2(str(source_path), str(target_path))

                return {
                    "status": "completed",
                    "rows": 0,
                    "start_date": None,
                    "end_date": None,
                }

            except OSError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                    gc.collect()
                else:
                    return {
                        "status": "failed",
                        "rows": 0,
                        "start_date": None,
                        "end_date": None,
                        "error": f"Could not update database: {e}",
                    }

        return {
            "status": "failed",
            "rows": 0,
            "start_date": None,
            "end_date": None,
        }

    def run_update(self, **kwargs: Any) -> dict[str, Any]:
        """Run update (same as run for file operations)."""
        return self.run(**kwargs)

    def is_up_to_date(self) -> bool:
        """Check if SQLite database file is up-to-date.

        Uses file modification time with T-1 check.
        """
        target_path = pathlib.Path(self.target_path)

        if not target_path.exists():
            return False

        # Get modification time
        mtime = target_path.stat().st_mtime
        mod_date = datetime.date.fromtimestamp(mtime)

        today = datetime.datetime.now().date()
        yesterday = today - datetime.timedelta(days=1)

        return mod_date >= yesterday
