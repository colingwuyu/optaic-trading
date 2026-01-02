"""Base Pipeline Implementation.

Abstract base class for all data pipelines.
Ported from optaic-v0/data/pipeline.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


class DataPipeline(ABC):
    """Abstract base class for data pipelines.

    Pipelines follow ETL pattern:
    1. extract() - Get raw data from source
    2. transform() - Clean and transform data
    3. run() - Execute full pipeline and save result

    Subclasses must implement:
    - extract(**kwargs) -> Any
    - transform(raw_data, **kwargs) -> pd.DataFrame
    - run_update() -> dict (for incremental updates)

    The run() method provides a standard flow that:
    - Calls extract() and transform()
    - Saves to the configured store
    - Returns run statistics

    Unlike optaic-v0, we don't have a status_store or data_api here.
    The service layer handles those concerns.
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize pipeline.

        Args:
            resource_id: Unique identifier for this pipeline instance
            config: Pipeline configuration
            store: Optional store for saving results
            **kwargs: Additional configuration
        """
        self.resource_id = resource_id
        self.config = config
        self.store = store
        self.extra_config = kwargs

    @abstractmethod
    def extract(self, **kwargs: Any) -> Any:
        """Extract raw data from source.

        Returns:
            Raw data (format depends on pipeline type)
        """

    @abstractmethod
    def transform(self, raw_data: Any, **kwargs: Any) -> "pd.DataFrame":
        """Transform raw data into DataFrame.

        Args:
            raw_data: Output from extract()
            **kwargs: Additional parameters

        Returns:
            Transformed DataFrame
        """

    def run(
        self,
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute full pipeline: extract -> transform -> save.

        Args:
            mode: Write mode ("overwrite" or "append")
            **kwargs: Additional parameters for extract/transform

        Returns:
            Run statistics (status, rows, start_date, end_date)
        """
        import pandas as pd

        # 1. Extract
        raw = self.extract(**kwargs)

        # 2. Transform
        df = self.transform(raw_data=raw, **kwargs)

        if df is None or df.empty:
            return {"status": "empty", "rows": 0, "start_date": None, "end_date": None}

        # 3. Save (if store is configured)
        if self.store is not None:
            self.store.write(df, mode=mode)

        # 4. Infer dates
        start_date = None
        end_date = None
        last_data_date = None

        if not df.empty:
            if isinstance(df.index, pd.DatetimeIndex):
                start_date = df.index.min()
                end_date = df.index.max()
                last_data_date = end_date.to_pydatetime() if end_date else None
            elif "date" in df.columns:
                start_date = df["date"].min()
                end_date = df["date"].max()
                try:
                    last_data_date = pd.to_datetime(end_date).to_pydatetime()
                except Exception:
                    last_data_date = self._get_last_data_date(df)
            else:
                last_data_date = self._get_last_data_date(df)

        return {
            "status": "completed",
            "rows": len(df),
            "start_date": start_date,
            "end_date": end_date,
            "last_data_date": last_data_date,
        }

    def run_update(self, **kwargs: Any) -> dict[str, Any]:
        """Run incremental update (default: full run).

        Override in subclasses for true incremental behavior.
        """
        return self.run(**kwargs)

    def is_up_to_date(self) -> bool:
        """Check if pipeline data is up-to-date.

        Override in subclasses for specific freshness logic.
        Default returns True (always up-to-date).
        """
        return True

    def _get_last_data_date(self, df: "pd.DataFrame") -> datetime | None:
        """Extract the latest date from a DataFrame.

        Args:
            df: DataFrame to inspect

        Returns:
            Latest date or None
        """
        import pandas as pd

        if df.empty:
            return None

        # Try DatetimeIndex
        if isinstance(df.index, pd.DatetimeIndex):
            return df.index.max().to_pydatetime()

        # Try common date columns
        for col in ["date", "Date", "DATE", "timestamp", "release_date"]:
            if col in df.columns:
                try:
                    return pd.to_datetime(df[col]).max().to_pydatetime()
                except Exception:
                    continue

        return None
