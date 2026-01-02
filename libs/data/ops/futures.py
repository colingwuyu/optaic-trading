"""Futures Rolling Operators.

Operators for computing continuous futures returns from raw contract prices,
active contract info, and contract date tables.

Ported from optaic-v0/dev_tools/src/function/library/future_ops.py.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.data.ops import register_op

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


def _get_contract_config(contract_name: str) -> RollConfig:
    """Get roll configuration for a specific contract."""
    config = _load_futures_config()
    defaults = config.get("defaults", {})
    contracts_config = config.get("contracts", {})
    c = contracts_config.get(contract_name, {})

    return RollConfig(
        roll_from=c.get("roll_from", defaults.get("roll_from", 1)),
        roll_to=c.get("roll_to", defaults.get("roll_to", 1)),
        roll_option=c.get("roll_option", defaults.get("roll_option", 3)),
        num_days=c.get("num_days", defaults.get("num_days", 5)),
        day_method=c.get("day_method", defaults.get("day_method", "C")),
    )


def _parse_contract_code(contracts: list[str], option: str = "contract_code") -> list[str]:
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
    name: str, roll_from: int, roll_to: int
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


def _roll_single_contract(
    contract_name: str,
    price_table: "pd.DataFrame",
    historical_active_contract: "pd.DataFrame",
    date_table: "pd.DataFrame",
    ticker_col: str,
) -> tuple["pd.Series | None", "pd.Series | None"]:
    """Roll a single contract and return (return_series, return_with_nan_series)."""
    import numpy as np
    import pandas as pd
    from pandas.tseries.offsets import BDay

    cfg = _get_contract_config(contract_name)
    temp_date_table = date_table[date_table["generic_code"] == contract_name].copy()

    # Fallback for Index vs Comdty naming
    if temp_date_table.empty and "Index" in contract_name:
        alt_name = contract_name.replace("Index", "Comdty")
        temp_date_table = date_table[date_table["generic_code"] == alt_name].copy()

    if temp_date_table.empty:
        return None, None

    if cfg.roll_from != cfg.roll_to:
        return None, None

    contract_tickers, front_contract_generic_1 = _get_required_contract(
        contract_name, cfg.roll_from, cfg.roll_to
    )

    # Ensure we have data
    if not all(c in price_table.columns for c in contract_tickers):
        return None, None

    if front_contract_generic_1 not in historical_active_contract.columns:
        return None, None

    absolute_return_list = {"ED Comdty", "ER Comdty", "L Comdty"}

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
            min_maturity["roll_date"] = min_maturity["maturitydate"] - subtract_delta

            ticker_to_roll_map = min_maturity.set_index("active_contract")["roll_date"]
            temp_date_table["roll_date"] = temp_date_table[ticker_col].map(
                ticker_to_roll_map
            )
        else:
            return None, None

        # Ensure roll_date is normalized datetime
        if "roll_date" in temp_date_table.columns:
            temp_date_table["roll_date"] = pd.to_datetime(
                temp_date_table["roll_date"]
            ).dt.normalize()

        # 4. Merge Data (Price + Active + DateTable Info)
        price_history_final = unfill_price_history.join(
            active_contract_date, how="left"
        ).ffill()

        # Merge DateTable info (Roll Date)
        dt_info = temp_date_table.set_index(ticker_col)[["roll_date"]]
        price_history_final["roll_date"] = price_history_final["active_contract"].map(
            dt_info["roll_date"]
        )

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
            # Absolute Differences
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
            # Percentage Returns
            price_history_final["front_return"] = (
                price_history_final[c_front] / price_history_final[c_front].shift(1)
            ) - 1
            price_history_final["far_return"] = (
                price_history_final[c_far] / price_history_final[c_far].shift(1)
            ) - 1
            price_history_final["cross_return"] = (
                price_history_final[c_front] / price_history_final[c_far].shift(1)
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

        # 8. Recalibration for Absolute Returns (Special Logic)
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
                / price_history_final[f"{contract_name}recalibrated_level"].shift(1)
            ) - 1

        # 9. NaN Handling and Masking
        nan_mask_original_price = unfill_price_history[c_front].isna()
        ret_col = f"{contract_name}_return"
        ret_with_nan_col = f"{contract_name}_return_with_nan"

        price_history_final[ret_with_nan_col] = price_history_final[ret_col].where(
            ~nan_mask_original_price, np.nan
        )

        nan_mask_active = price_history_final["active_contract"].isna()
        price_history_final[ret_col] = price_history_final[ret_col].where(
            ~nan_mask_active, np.nan
        )
        price_history_final[ret_with_nan_col] = price_history_final[
            ret_with_nan_col
        ].where(~nan_mask_active, np.nan)

        return price_history_final[ret_col], price_history_final[ret_with_nan_col]

    except Exception:
        return None, None


@register_op("ROLL_FUTURES", category="Futures")
def roll_futures_op(
    price_table: "pd.DataFrame",
    historical_active_contract: "pd.DataFrame",
    date_table: "pd.DataFrame",
    tickers: "list[str] | str | None" = None,
    return_with_nan: bool = False,
) -> "pd.DataFrame":
    """Roll futures contracts to compute continuous returns.

    This operator computes continuous futures returns by rolling contracts
    based on the configuration in futures.yaml. It handles roll logic including
    front/far contract transitions and special absolute return contracts.

    Args:
        price_table: DataFrame with contract prices (columns = contract tickers).
        historical_active_contract: DataFrame with active contract tickers over time.
        date_table: DataFrame with contract dates (FUT_NOTICE_FIRST, LAST_TRADEABLE_DT).
        tickers: List of contract tickers to process (e.g., ["ES Index", "NQ Index"]).
                 If None, processes all contracts from futures.yaml config.
                 Can also be a comma-separated string.
        return_with_nan: If True, returns series with NaNs where active contract missing.

    Returns:
        pd.DataFrame: Continuous returns for each contract (columns = contract names).

    Example:
        ROLL_FUTURES($future_price_atomic, $historical_active_contract_atomic, $future_date_atomic)
        ROLL_FUTURES($future_price_atomic, $historical_active_contract_atomic, $future_date_atomic, "ES Index,NQ Index")
    """
    import pandas as pd

    config = _load_futures_config()
    contracts_config = config.get("contracts", {})

    # Ensure index is datetime
    price_table = price_table.copy()
    historical_active_contract = historical_active_contract.copy()
    date_table = date_table.copy()

    price_table.index = pd.to_datetime(price_table.index)
    historical_active_contract.index = pd.to_datetime(historical_active_contract.index)

    # Prepare Date Table
    for col in ["FUT_NOTICE_FIRST", "LAST_TRADEABLE_DT"]:
        if col in date_table.columns:
            date_table[col] = pd.to_datetime(date_table[col])

    ticker_col = "INTERNAL_TICKER" if "INTERNAL_TICKER" in date_table.columns else "TICKER"
    date_table["generic_code"] = _parse_contract_code(
        date_table[ticker_col].to_list(), option="generic_code"
    )

    # Initialize Outputs
    output_without_nan = pd.DataFrame(index=price_table.index)
    output_with_nan = pd.DataFrame(index=price_table.index)

    # Determine Contracts to Process
    contracts_to_process = list(contracts_config.keys()) if contracts_config else []

    if tickers:
        # Handle string input (comma-separated)
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.split(",")]

        user_contracts = []
        for t in tickers:
            # Normalization: ES1 Index -> ES Index
            t_code = re.sub(r"\s+", " ", re.sub(r"[0-9]+", "", t)).strip()
            if t_code in contracts_to_process:
                user_contracts.append(t_code)
        contracts_to_process = user_contracts

    # Process each contract
    for contract_name in contracts_to_process:
        ret_series, ret_with_nan_series = _roll_single_contract(
            contract_name,
            price_table,
            historical_active_contract,
            date_table,
            ticker_col,
        )

        if ret_series is not None:
            output_without_nan[contract_name] = ret_series
        if ret_with_nan_series is not None:
            output_with_nan[contract_name] = ret_with_nan_series

    return output_with_nan if return_with_nan else output_without_nan


@register_op("ROLL_FUTURES_SINGLE", category="Futures")
def roll_futures_single_op(
    price_table: "pd.DataFrame",
    historical_active_contract: "pd.DataFrame",
    date_table: "pd.DataFrame",
    ticker: str,
    return_with_nan: bool = False,
) -> "pd.Series":
    """Roll a single futures contract to compute continuous returns.

    Same logic as ROLL_FUTURES but returns a single Series for one contract.

    Args:
        price_table: DataFrame with contract prices.
        historical_active_contract: DataFrame with active contract tickers.
        date_table: DataFrame with contract dates.
        ticker: Single contract ticker (e.g., "ES Index").
        return_with_nan: If True, returns series with NaNs preserved.

    Returns:
        pd.Series: Continuous returns for the contract.

    Example:
        ROLL_FUTURES_SINGLE($future_price_atomic, $historical_active_contract_atomic, $future_date_atomic, "ES Index")
    """
    import pandas as pd

    result = roll_futures_op(
        price_table,
        historical_active_contract,
        date_table,
        tickers=[ticker],
        return_with_nan=return_with_nan,
    )

    # Normalize ticker to generic code for column lookup
    ticker_normalized = re.sub(r"\s+", " ", re.sub(r"[0-9]+", "", ticker)).strip()

    if ticker_normalized in result.columns:
        return result[ticker_normalized]
    elif len(result.columns) == 1:
        return result.iloc[:, 0]
    else:
        return pd.Series(dtype=float, index=result.index, name=ticker_normalized)


@register_op("FUTURES_UNIVERSE", category="Futures")
def futures_universe_op() -> list[str]:
    """Get the list of all available futures contracts from config.

    Returns:
        list[str]: List of contract names configured in futures.yaml.

    Example:
        FUTURES_UNIVERSE()
    """
    config = _load_futures_config()
    contracts_config = config.get("contracts", {})
    return list(contracts_config.keys())
