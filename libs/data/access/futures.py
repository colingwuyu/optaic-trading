"""Futures Accessor Implementation.

Handles continuous contract rolling logic on-the-fly.
Ported from optaic-v0/dev_tools/src/data/access/futures.py.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict, Field

from libs.data.access.base import BaseAccessor, BaseRequest
from libs.data.registry import register_accessor

if TYPE_CHECKING:
    import pandas as pd

# Config loading deferred to avoid import issues
_futures_config: dict[str, Any] | None = None


def _load_futures_config() -> dict[str, Any]:
    """Load futures config lazily."""
    global _futures_config
    if _futures_config is not None:
        return _futures_config

    try:
        import yaml

        # Look for config in standard locations
        config_paths = [
            Path("config/futures.yaml"),
            Path("configs/futures.yaml"),
            Path.home() / ".optaic" / "futures.yaml",
        ]

        for config_path in config_paths:
            if config_path.exists():
                with open(config_path) as f:
                    _futures_config = yaml.safe_load(f) or {}
                return _futures_config

        _futures_config = {}
        return _futures_config

    except Exception:
        _futures_config = {}
        return _futures_config


@dataclass
class RollConfig:
    """Configuration for futures rolling."""

    roll_from: int
    roll_to: int
    roll_option: int
    num_days: int
    day_method: str


class FuturesRequest(BaseRequest):
    """Request model for GenericFuturesAccessor."""

    tickers: list[str] = Field(
        default_factory=list,
        description="Tickers to retrieve (e.g., ['ES Index', 'NQ Index']).",
    )
    return_with_nan: bool = Field(
        default=False,
        description="Return series with NaNs preserved where active contract is missing.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2020-01-01",
                    "end_date": "2024-12-31",
                    "tickers": ["ES Index", "NQ Index"],
                    "return_with_nan": False,
                }
            ]
        }
    )


@register_accessor("GenericFuturesAccessor")
class GenericFuturesAccessor(BaseAccessor):
    """Accessor for Futures Data with continuous contract rolling.

    Handles continuous contract rolling logic on-the-fly.
    Requires constituent datasets:
    - future_price_atomic: Contract prices
    - historical_active_contract_atomic: Active contract tickers
    - future_date_atomic: Contract dates

    Config Options:
    - constituents: Dict mapping component names to dataset resource IDs
    """

    def __init__(
        self,
        resource_id: str,
        config: dict[str, Any],
        store: Any | None = None,
        context_loader: Any | None = None,
        **kwargs: Any,
    ):
        """Initialize GenericFuturesAccessor.

        Args:
            resource_id: Accessor resource ID
            config: Configuration
            store: Optional store
            context_loader: Callable to load constituent datasets
            **kwargs: Additional config
        """
        super().__init__(resource_id, config, store, **kwargs)

        self.context_loader = context_loader
        self.futures_config = _load_futures_config()
        self.defaults = self.futures_config.get("defaults", {})
        self.contracts_config = self.futures_config.get("contracts", {})
        self.settings = self.futures_config.get("settings", {})

    def get_request_model(self) -> type[FuturesRequest]:
        """Return the request model."""
        return FuturesRequest

    def get_output_columns(self) -> list[str]:
        """Returns available contract names from config."""
        return list(self.contracts_config.keys())

    def get(
        self,
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
        tickers: list[str] | None = None,
        return_with_nan: bool = False,
        **kwargs: Any,
    ) -> "pd.DataFrame":
        """Returns Continuous Returns.

        Args:
            start_date: Start date filter
            end_date: End date filter
            tickers: List of contract tickers to process
            return_with_nan: If True, preserves NaNs where active contract is missing
            **kwargs: Additional arguments

        Returns:
            DataFrame with continuous returns for each contract
        """
        import pandas as pd

        # Load constituent datasets
        if self.context_loader is None:
            raise ValueError("context_loader is required for GenericFuturesAccessor")

        constituents = self.config.get("constituents", {})

        # Load required tables
        price_table = self._load_constituent(
            constituents.get("future_price_atomic", "future_price_atomic"),
            start_date,
            end_date,
            kwargs.get("as_of_date"),
        )
        hist_active = self._load_constituent(
            constituents.get(
                "historical_active_contract_atomic", "historical_active_contract_atomic"
            ),
            start_date,
            end_date,
            kwargs.get("as_of_date"),
        )
        date_table = self._load_constituent(
            constituents.get("future_date_atomic", "future_date_atomic"),
            None,
            None,
            kwargs.get("as_of_date"),
        )

        if price_table.empty:
            return pd.DataFrame()

        output_without_nan, output_with_nan = self._roll_prices(
            price_table, hist_active, date_table, start_date, end_date, tickers
        )

        return output_with_nan if return_with_nan else output_without_nan

    def _load_constituent(
        self,
        name: str,
        start_date: dt.date | None,
        end_date: dt.date | None,
        as_of_date: dt.date | None,
    ) -> "pd.DataFrame":
        """Load a constituent dataset."""
        import pandas as pd

        try:
            return self.context_loader(
                name,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
            )
        except Exception:
            return pd.DataFrame()

    def _get_contract_config(self, contract_name: str) -> RollConfig:
        """Get roll configuration for a specific contract."""
        c = self.contracts_config.get(contract_name, {})

        return RollConfig(
            roll_from=c.get("roll_from", self.defaults.get("roll_from", 1)),
            roll_to=c.get("roll_to", self.defaults.get("roll_to", 1)),
            roll_option=c.get("roll_option", self.defaults.get("roll_option", 3)),
            num_days=c.get("num_days", self.defaults.get("num_days", 5)),
            day_method=c.get("day_method", self.defaults.get("day_method", "C")),
        )

    def _parse_contract_code(
        self, contracts: list[str], option: str = "contract_code"
    ) -> list[str]:
        """Parse contract codes to extract generic or specific codes."""
        parsed = []

        for x in contracts:
            parts = x.split()

            if len(parts) < 2:
                parsed.append(x)
                continue

            stripped_first = re.sub(r"[0-9]+", "", parts[0])

            if option == "generic_code":
                if len(parts[0]) > 1:  # e.g. ES1
                    parsed.append(stripped_first[:-1] + " " + parts[-1])
                else:  # e.g. Z 1
                    parsed.append(stripped_first + " " + parts[-1])

            elif option == "contract_code":
                if len(parts[0]) > 1:
                    parsed.append(parts[0] + " " + parts[-1])
                else:
                    if len(parts) > 2:
                        parsed.append(parts[0] + " " + parts[1] + " " + parts[-1])
                    else:
                        parsed.append(x)

        return parsed

    def _get_required_contract(
        self, name: str, roll_from: int, roll_to: int
    ) -> tuple[list[str], str]:
        """Get list of required contract tickers and front contract name."""
        parts = name.split()
        root = parts[0]
        suffix = parts[-1]
        is_attached = len(root) > 1
        contracts = []

        for x in range(roll_to - roll_from + 2):
            idx = roll_to + x
            if is_attached:
                contracts.append(f"{root}{idx} {suffix}")
            else:
                contracts.append(f"{root} {idx} {suffix}")

        front_contract = f"{root}1 {suffix}" if is_attached else f"{root} 1 {suffix}"

        return contracts, front_contract

    def _roll_prices(
        self,
        price_table: "pd.DataFrame",
        historical_active_contract: "pd.DataFrame",
        date_table: "pd.DataFrame",
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
        tickers: list[str] | None = None,
    ) -> tuple["pd.DataFrame", "pd.DataFrame"]:
        """Roll prices to compute continuous returns."""
        import numpy as np
        import pandas as pd
        from pandas.tseries.offsets import BDay

        # Set defaults if None
        if start_date is None:
            start_date = self.settings.get("start_date", "1900-01-01")
        if end_date is None:
            end_date = dt.date.today()

        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)

        # Ensure index is datetime
        price_table = price_table.copy()
        price_table.index = pd.to_datetime(price_table.index)
        historical_active_contract = historical_active_contract.copy()
        historical_active_contract.index = pd.to_datetime(
            historical_active_contract.index
        )

        # Filter Date Ranges
        price_table = price_table[
            (price_table.index >= start_ts) & (price_table.index <= end_ts)
        ]
        historical_active_contract = historical_active_contract[
            (historical_active_contract.index >= start_ts)
            & (historical_active_contract.index <= end_ts)
        ]

        # Prepare Date Table
        date_table = date_table.copy()
        for col in ["FUT_NOTICE_FIRST", "LAST_TRADEABLE_DT"]:
            if col in date_table.columns:
                date_table[col] = pd.to_datetime(date_table[col])

        ticker_col = (
            "INTERNAL_TICKER" if "INTERNAL_TICKER" in date_table.columns else "TICKER"
        )
        date_table["generic_code"] = self._parse_contract_code(
            date_table[ticker_col].to_list(), option="generic_code"
        )

        # Initialize Outputs
        output_without_nan = pd.DataFrame(index=price_table.index)
        output_with_nan = pd.DataFrame(index=price_table.index)

        # Determine Contracts to Process
        contracts_to_process = (
            list(self.contracts_config.keys()) if self.contracts_config else []
        )
        if tickers:
            user_contracts_to_process = []
            for t in tickers:
                # Normalization: ES1 Index -> ES Index
                t_code = re.sub(r"\s+", " ", re.sub(r"[0-9]+", "", t)).strip()
                if t_code in contracts_to_process:
                    user_contracts_to_process.append(t_code)
            contracts_to_process = user_contracts_to_process

        absolute_return_list = {"ED Comdty", "ER Comdty", "L Comdty"}

        for contract_name in contracts_to_process:
            cfg = self._get_contract_config(contract_name)
            temp_date_table = date_table[
                date_table["generic_code"] == contract_name
            ].copy()

            # Fallback for Index vs Comdty naming
            if temp_date_table.empty and "Index" in contract_name:
                alt_name = contract_name.replace("Index", "Comdty")
                temp_date_table = date_table[
                    date_table["generic_code"] == alt_name
                ].copy()

            if temp_date_table.empty:
                continue

            if cfg.roll_from != cfg.roll_to:
                continue

            contract_tickers, front_contract_generic_1 = self._get_required_contract(
                contract_name, cfg.roll_from, cfg.roll_to
            )

            # Ensure we have data
            if not all(c in price_table.columns for c in contract_tickers):
                continue

            if front_contract_generic_1 not in historical_active_contract.columns:
                continue

            try:
                # 1. Prepare Price History
                unfill_price_history = price_table[contract_tickers].copy()

                # 2. Prepare Active Contract
                active_contract_date = historical_active_contract[
                    [front_contract_generic_1]
                ].copy()
                active_contract_date = active_contract_date.rename(
                    columns={front_contract_generic_1: "active_contract"}
                )

                # 3. Calculate Roll Dates
                subtract_delta = (
                    dt.timedelta(days=cfg.num_days)
                    if cfg.day_method == "C"
                    else BDay(cfg.num_days)
                )

                if cfg.roll_option == 1:
                    temp_date_table["roll_date"] = (
                        temp_date_table["FUT_NOTICE_FIRST"] - subtract_delta
                    )
                elif cfg.roll_option == 2:
                    temp_date_table["roll_date"] = (
                        temp_date_table["LAST_TRADEABLE_DT"] - subtract_delta
                    )
                elif cfg.roll_option == 3:
                    temp_date_table["roll_date"] = (
                        np.minimum(
                            temp_date_table["FUT_NOTICE_FIRST"],
                            temp_date_table["LAST_TRADEABLE_DT"],
                        )
                        - subtract_delta
                    )
                elif cfg.roll_option == 4:
                    maturity_df = active_contract_date.dropna().copy()
                    maturity_df["isexpired"] = maturity_df["active_contract"].shift(-1)
                    mask = maturity_df["isexpired"] != maturity_df["active_contract"]
                    maturity_df["maturitydate"] = maturity_df.index
                    min_maturity = maturity_df[mask].copy()
                    min_maturity["roll_date"] = (
                        min_maturity["maturitydate"] - subtract_delta
                    )
                    ticker_to_roll_map = min_maturity.set_index("active_contract")[
                        "roll_date"
                    ]
                    temp_date_table["roll_date"] = temp_date_table[ticker_col].map(
                        ticker_to_roll_map
                    )
                else:
                    continue

                # Normalize roll_date
                if "roll_date" in temp_date_table.columns:
                    temp_date_table["roll_date"] = pd.to_datetime(
                        temp_date_table["roll_date"]
                    ).dt.normalize()

                # 4. Merge Data
                price_history_final = unfill_price_history.join(
                    active_contract_date, how="left"
                ).ffill()

                dt_info = temp_date_table.set_index(ticker_col)[["roll_date"]]
                price_history_final["roll_date"] = price_history_final[
                    "active_contract"
                ].map(dt_info["roll_date"])

                # 5. Calculate Signals
                price_history_final["roll_signal_one"] = (
                    price_history_final["roll_date"] < price_history_final.index
                )
                price_history_final["roll_signal_two"] = price_history_final[
                    "active_contract"
                ] != price_history_final["active_contract"].shift(1)

                # 6. Returns Calculation
                c_front = contract_tickers[0]
                c_far = contract_tickers[1]

                if contract_name in absolute_return_list:
                    price_history_final["front_return"] = price_history_final[
                        c_front
                    ] - price_history_final[c_front].shift(1)
                    price_history_final["far_return"] = price_history_final[
                        c_far
                    ] - price_history_final[c_far].shift(1)
                    price_history_final["cross_return"] = price_history_final[
                        c_front
                    ] - price_history_final[c_far].shift(1)
                else:
                    price_history_final["front_return"] = (
                        price_history_final[c_front]
                        / price_history_final[c_front].shift(1)
                    ) - 1
                    price_history_final["far_return"] = (
                        price_history_final[c_far] / price_history_final[c_far].shift(1)
                    ) - 1
                    price_history_final["cross_return"] = (
                        price_history_final[c_front]
                        / price_history_final[c_far].shift(1)
                    ) - 1

                # 7. Construct Composite Return Series
                s1 = price_history_final["roll_signal_one"]
                s2 = price_history_final["roll_signal_two"]

                conditions = [(s1 & ~s2), s2]
                choices = [
                    price_history_final["far_return"],
                    price_history_final["cross_return"],
                ]
                price_history_final[f"{contract_name}_return"] = np.select(
                    conditions, choices, default=price_history_final["front_return"]
                )

                # 8. Recalibration for Absolute Returns
                if contract_name in absolute_return_list:
                    last_idx = -1
                    if (
                        price_history_final["roll_date"].iloc[last_idx]
                        == price_history_final.index[last_idx]
                    ) or (price_history_final["roll_signal_one"].iloc[last_idx]):
                        level = price_history_final[c_far].iloc[last_idx]
                    else:
                        level = price_history_final[c_front].iloc[last_idx]

                    vals = (
                        level
                        - price_history_final[f"{contract_name}_return"][::-1]
                        .cumsum()[::-1]
                        .to_numpy()[1:]
                    )
                    vals = np.append(vals, level)
                    price_history_final[f"{contract_name}recalibrated_level"] = vals

                    price_history_final[f"{contract_name}_return"] = (
                        price_history_final[f"{contract_name}recalibrated_level"]
                        / price_history_final[
                            f"{contract_name}recalibrated_level"
                        ].shift(1)
                    ) - 1

                # 9. NaN Handling
                nan_mask_original_price = unfill_price_history[c_front].isna()
                ret_col = f"{contract_name}_return"
                ret_with_nan_col = f"{contract_name}_return_with_nan"

                price_history_final[ret_with_nan_col] = price_history_final[
                    ret_col
                ].where(~nan_mask_original_price, np.nan)

                nan_mask_active = price_history_final["active_contract"].isna()
                price_history_final[ret_col] = price_history_final[ret_col].where(
                    ~nan_mask_active, np.nan
                )
                price_history_final[ret_with_nan_col] = price_history_final[
                    ret_with_nan_col
                ].where(~nan_mask_active, np.nan)

                # 10. Accumulate Results
                output_without_nan[contract_name] = price_history_final[ret_col]
                output_with_nan[contract_name] = price_history_final[ret_with_nan_col]

            except Exception:
                continue

        return output_without_nan, output_with_nan
