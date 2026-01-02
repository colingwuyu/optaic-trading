"""Bloomberg Pipeline Implementation.

Pipeline for ingesting market data from Bloomberg Terminal.
Ported from optaic-v0/dev_tools/src/pipelines/data/bloomberg.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from libs.data.pipelines.base import DataPipeline
from libs.data.registry import register_pipeline

if TYPE_CHECKING:
    import pandas as pd

# Try importing xbbg
try:
    from xbbg import blp
except ImportError:
    blp = None  # type: ignore


@register_pipeline("BloombergPipeline")
class BloombergPipeline(DataPipeline):
    """Pipeline for ingesting market data from Bloomberg Terminal.

    Config Options:
    - ticker: Bloomberg ticker (e.g., "SPX Index")
    - fields: Dict mapping BBG field to renamed name, or list of fields
        Examples:
        - {"PX_LAST": "close", "PX_OPEN": "open"}  # New format
        - ["PX_LAST", "PX_OPEN"]  # Legacy format
    - rename_mapper: (Legacy) Rename mapping when fields is a list
    - primary_key: Date column name for index (default: "date")

    Requires:
    - xbbg package installed
    - Bloomberg Terminal or BAPI connection
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize BloombergPipeline.

        Args:
            resource_id: Pipeline resource ID
            config: Configuration containing 'ticker' and 'fields'
            store: Optional store for saving results
            **kwargs: Additional config
        """
        super().__init__(resource_id, config, store, **kwargs)

        if "ticker" not in config:
            raise ValueError("BloombergPipeline requires 'ticker' in config")
        if "fields" not in config:
            raise ValueError("BloombergPipeline requires 'fields' in config")

        self.ticker = config["ticker"]
        self.primary_key = config.get("primary_key", "date")
        self._fields_override = kwargs.get("fields")  # For subclass override

    def _resolve_fields_config(self) -> tuple[list[str], dict[str, str]]:
        """Resolve fields configuration into (field_list, rename_mapper).

        Supports both new dict format and legacy list+rename_mapper format.

        Returns:
            tuple: (list of BBG fields to fetch, dict mapping BBG field -> new name)
        """
        fields_config = self._fields_override or self.config.get("fields")

        if not fields_config:
            raise ValueError(f"No fields specified for {self.resource_id}")

        # New format: fields is a dict {BBG_FIELD: renamed_name_or_null}
        if isinstance(fields_config, dict):
            field_list = list(fields_config.keys())
            # Build rename mapper: only include entries where value is not None
            rename_mapper = {k: v for k, v in fields_config.items() if v is not None}
            return field_list, rename_mapper

        # Legacy format: fields is a list, rename_mapper is separate
        if isinstance(fields_config, list):
            rename_mapper = self.config.get("rename_mapper", {})
            return fields_config, rename_mapper

        raise ValueError(
            f"Invalid fields config type: {type(fields_config)}. Expected dict or list."
        )

    def extract(self, **kwargs: Any) -> "pd.DataFrame":
        """Extract data from Bloomberg.

        Args:
            **kwargs: Optional overrides:
                - start_date: Start date for data
                - end_date: End date for data

        Returns:
            Raw DataFrame from Bloomberg
        """
        if blp is None:
            raise ImportError(
                "xbbg package is required for Bloomberg data. Install with: pip install xbbg"
            )

        fields, _ = self._resolve_fields_config()

        start_date = kwargs.get("start_date", "1900-01-01")
        end_date = kwargs.get("end_date", "2100-01-01")

        df = blp.bdh(
            tickers=self.ticker,
            flds=fields,
            start_date=start_date,
            end_date=end_date,
        )

        return df

    def transform(self, raw_data: "pd.DataFrame", **kwargs: Any) -> "pd.DataFrame":
        """Transform Bloomberg data.

        Args:
            raw_data: Raw DataFrame from extract()
            **kwargs: Additional parameters

        Returns:
            Transformed DataFrame with proper column names
        """
        if raw_data is None or raw_data.empty:
            return raw_data

        df = raw_data.copy()

        # Flatten MultiIndex if needed (Bloomberg returns ticker as first level)
        if df.columns.nlevels > 1:
            df = df.droplevel(0, axis=1)

        # Apply rename mapper
        _, rename_mapper = self._resolve_fields_config()
        if rename_mapper:
            df = df.rename(columns=rename_mapper)

        df.index.name = self.primary_key

        return df

    def run_update(self, **kwargs: Any) -> dict[str, Any]:
        """Run incremental update.

        Fetches data starting from the last available date.
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

        # Determine incremental start
        last_date = df_existing.index.max()

        if pd.isna(last_date):
            return self.run(**kwargs)

        # Extract new data starting from last_date
        try:
            df_new_raw = self.extract(start_date=last_date)
        except Exception as e:
            return {
                "status": "failed",
                "rows": 0,
                "start_date": None,
                "end_date": None,
                "error": str(e),
            }

        if df_new_raw is None or df_new_raw.empty:
            return {
                "status": "up_to_date",
                "rows": 0,
                "start_date": last_date,
                "end_date": last_date,
            }

        # Transform
        df_new = self.transform(df_new_raw)

        # Deduplicate
        if isinstance(df_new.index, pd.DatetimeIndex):
            df_new = df_new[df_new.index > last_date]

        if df_new.empty:
            return {
                "status": "up_to_date",
                "rows": 0,
                "start_date": last_date,
                "end_date": last_date,
            }

        # Save append
        self.store.write(df_new, mode="append")

        return {
            "status": "updated",
            "rows": len(df_new),
            "start_date": df_new.index.min(),
            "end_date": df_new.index.max(),
        }

    def is_up_to_date(self) -> bool:
        """Check if Bloomberg data is up-to-date (T-1)."""
        import datetime

        import pandas as pd

        if self.store is None:
            return False

        try:
            df = self.store.read()
            if df is None or df.empty:
                return False

            # Get max date
            if isinstance(df.index, pd.DatetimeIndex):
                last_date = df.index.max()
            elif "date" in df.columns:
                last_date = pd.to_datetime(df["date"]).max()
            else:
                return True

            # Compare with T-1
            if isinstance(last_date, pd.Timestamp):
                last_date = last_date.date()

            today = datetime.datetime.now().date()
            yesterday = today - datetime.timedelta(days=1)

            return last_date >= yesterday

        except Exception:
            return False


@register_pipeline("OHLCVBloombergPipeline")
class OHLCVBloombergPipeline(BloombergPipeline):
    """Pre-configured pipeline for standard OHLCV data from Bloomberg.

    Fetches PX_OPEN, PX_HIGH, PX_LOW, PX_LAST, PX_VOLUME and renames to
    standard open, high, low, close, volume columns.
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize OHLCVBloombergPipeline.

        Args:
            resource_id: Pipeline resource ID
            config: Configuration (only 'ticker' required)
            store: Optional store for saving results
            **kwargs: Additional config
        """
        # Pre-configure OHLCV fields
        ohlcv_fields = {
            "PX_OPEN": "open",
            "PX_HIGH": "high",
            "PX_LOW": "low",
            "PX_LAST": "close",
            "PX_VOLUME": "volume",
        }

        super().__init__(
            resource_id,
            config,
            store,
            fields=ohlcv_fields,
            **kwargs,
        )
