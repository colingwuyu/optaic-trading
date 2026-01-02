"""FRED Pipeline Implementation.

Pipeline for ingesting economic data from FRED (Federal Reserve Economic Data).
Ported from optaic-v0/dev_tools/src/pipelines/data/fred.py.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from libs.data.pipelines.base import DataPipeline
from libs.data.registry import register_pipeline

if TYPE_CHECKING:
    import pandas as pd

# Try importing fredapi
try:
    from fredapi import Fred
except ImportError:
    Fred = None  # type: ignore


@register_pipeline("FredPipeline")
class FredPipeline(DataPipeline):
    """Pipeline for ingesting economic data from FRED.

    Config Options:
    - series_id: FRED series ID (e.g., "GDP", "CPIAUCSL")
    - vintage: If True, fetch all releases (vintage data)

    The pipeline fetches data from FRED and stores it with proper
    date indexing. For vintage data, it includes release_date column.
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize FredPipeline.

        Args:
            resource_id: Pipeline resource ID
            config: Configuration containing 'series_id' and optionally 'vintage'
            store: Optional store for saving results
            **kwargs: Additional config
        """
        super().__init__(resource_id, config, store, **kwargs)

        if "series_id" not in config:
            raise ValueError("FredPipeline requires 'series_id' in config")

        self.series_id = config["series_id"]
        self.vintage = config.get("vintage", False)

        # Initialize FRED client
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            self.fred = None
        elif Fred is not None:
            self.fred = Fred(api_key=api_key)
        else:
            self.fred = None

    def extract(self, **kwargs: Any) -> "pd.DataFrame":
        """Extract data from FRED API.

        Args:
            **kwargs: Optional overrides:
                - realtime_start: For vintage data
                - observation_start: For regular data

        Returns:
            Raw DataFrame from FRED
        """
        if self.fred is None:
            raise ValueError(
                "FRED API not initialized. Ensure 'fredapi' is installed and FRED_API_KEY is set."
            )

        # Allow overrides from kwargs
        realtime_start = kwargs.get("realtime_start")
        observation_start = kwargs.get("observation_start")

        if realtime_start:
            if hasattr(realtime_start, "strftime"):
                realtime_start = realtime_start.strftime("%Y-%m-%d")
        if observation_start:
            if hasattr(observation_start, "strftime"):
                observation_start = observation_start.strftime("%Y-%m-%d")

        max_retries = 5
        retry_delay = 1
        last_exception = None

        for attempt in range(max_retries):
            try:
                if self.vintage:
                    df = self.fred.get_series_all_releases(
                        self.series_id, realtime_start=realtime_start
                    )
                else:
                    series = self.fred.get_series(
                        self.series_id, observation_start=observation_start
                    )
                    df = series.to_frame(name="value")
                    df = df.reset_index()
                    df.columns = ["date", "value"]
                return df

            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    import time

                    time.sleep(retry_delay)

        raise ConnectionError(
            f"Failed to download {self.series_id} from FRED after {max_retries} attempts."
        ) from last_exception

    def transform(self, raw_data: "pd.DataFrame", **kwargs: Any) -> "pd.DataFrame":
        """Transform FRED data into standard format.

        Args:
            raw_data: Raw DataFrame from extract()
            **kwargs: Additional parameters

        Returns:
            Transformed DataFrame with proper date indexing
        """
        import pandas as pd

        if raw_data is None or raw_data.empty:
            return pd.DataFrame()

        df = raw_data.copy()

        if self.vintage:
            # Vintage data: date, realtime_start, value
            if "realtime_start" in df.columns:
                df = df.rename(columns={"realtime_start": "release_date"})

            df["date"] = pd.to_datetime(df["date"])
            if "release_date" in df.columns:
                df["release_date"] = pd.to_datetime(df["release_date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")

            df = df.dropna(subset=["date"])
            df = df.set_index("date")
        else:
            # Regular time series
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")

        return df

    def run_update(self, **kwargs: Any) -> dict[str, Any]:
        """Run incremental update for FRED data.

        For vintage data, fetches new releases since last release_date.
        For regular data, fetches new observations since last date.
        """
        import pandas as pd

        if self.store is None:
            return self.run(**kwargs)

        # Get existing data
        try:
            df_existing = self.store.read()
        except Exception:
            return self.run(**kwargs)

        if df_existing is None or df_existing.empty:
            return self.run(**kwargs)

        if self.vintage:
            if "release_date" not in df_existing.columns:
                return self.run(**kwargs)

            last_release = df_existing["release_date"].max()

            # Extract incremental
            df_new_raw = self.extract(realtime_start=last_release)
            df_new = self.transform(df_new_raw)

            # Deduplicate
            if "release_date" in df_new.columns:
                df_new = df_new[df_new["release_date"] > last_release]

            if df_new.empty:
                return {
                    "status": "source_delayed",
                    "rows": 0,
                    "start_date": None,
                    "end_date": None,
                }

            # Append
            self.store.write(df_new, mode="append")

            start_date = df_new.index.min() if hasattr(df_new, "index") else None
            end_date = df_new.index.max() if hasattr(df_new, "index") else None

            return {
                "status": "updated",
                "rows": len(df_new),
                "start_date": start_date,
                "end_date": end_date,
            }
        else:
            # Regular time series
            last_date = df_existing.index.max()

            if pd.isna(last_date):
                return self.run(**kwargs)

            df_new_raw = self.extract(observation_start=last_date)
            df_new = self.transform(df_new_raw)

            # Deduplicate
            df_new = df_new[df_new.index > last_date]

            if df_new.empty:
                return {
                    "status": "source_delayed",
                    "rows": 0,
                    "start_date": last_date,
                    "end_date": last_date,
                }

            self.store.write(df_new, mode="append")

            return {
                "status": "updated",
                "rows": len(df_new),
                "start_date": df_new.index.min(),
                "end_date": df_new.index.max(),
            }

    def is_up_to_date(self) -> bool:
        """Check if FRED data is up-to-date.

        Uses T-1 check by default.
        """
        import datetime

        import pandas as pd

        if self.store is None:
            return False

        try:
            df = self.store.read()
            if df is None or df.empty:
                return False

            # Determine last data date
            if isinstance(df.index, pd.DatetimeIndex):
                last_date = df.index.max()
            elif "date" in df.columns:
                last_date = pd.to_datetime(df["date"]).max()
            elif "release_date" in df.columns:
                last_date = pd.to_datetime(df["release_date"]).max()
            else:
                return True

            if isinstance(last_date, pd.Timestamp):
                last_date = last_date.date()

            # T-1 check
            today = datetime.datetime.now().date()
            yesterday = today - datetime.timedelta(days=1)

            return last_date >= yesterday

        except Exception:
            return False
