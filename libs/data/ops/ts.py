"""Time Series Operators.

Advanced time series operations for data manipulation.
Ported from optaic-v0/function/library/ts_ops.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from libs.data.ops.core import register_op

if TYPE_CHECKING:
    import pandas as pd


@register_op("TS_CONCAT", category="Time Series")
def ts_concat_op(
    *args: "pd.DataFrame | pd.Series",
) -> "pd.DataFrame | pd.Series":
    """Concatenate multiple time series to expand historical data.

    Uses the date index to concat rows. For each dataframe, uses dates from
    the previous dataframe that are before the current dataframe's earliest date.

    Processing order (reverse):
    - Start with the last dataframe (z) as the base
    - For each previous dataframe (y, x, ...):
      - Filter rows where date < earliest date of current result
      - Prepend those rows to extend history

    Args:
        *args: Variable number of DataFrames or Series with DatetimeIndex,
               ordered from oldest source (x) to newest/primary (z)

    Returns:
        Concatenated data with extended history

    Example:
        x: 2020-01-01 to 2022-12-31 (old dataset)
        y: 2022-01-01 to 2023-12-31 (intermediate dataset)
        z: 2023-06-01 to 2024-12-31 (newest dataset)

        Result:
        - Start with z (2023-06-01 onwards)
        - Add y rows before 2023-06-01 (2022-01-01 to 2023-05-31)
        - Add x rows before 2022-01-01 (2020-01-01 to 2021-12-31)
        - Final: 2020-01-01 to 2024-12-31

    Usage:
        TS_CONCAT($old_data, $new_data)
    """
    import pandas as pd

    if len(args) == 0:
        raise ValueError("TS_CONCAT requires at least one DataFrame or Series")

    if len(args) == 1:
        return args[0]

    # Convert all inputs to DataFrames and track if all were Series
    all_series = all(isinstance(arg, pd.Series) for arg in args)
    series_name = None

    dataframes = []
    for i, data in enumerate(args):
        if isinstance(data, pd.Series):
            series_name = data.name  # Preserve Series name for potential return
            df = data.to_frame(name=data.name or "value")
        elif isinstance(data, pd.DataFrame):
            df = data
        else:
            raise TypeError(
                f"Argument {i} must be a DataFrame or Series, got {type(data)}"
            )

        if df.empty:
            continue

        # Ensure index is datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index)
        dataframes.append(df)

    if len(dataframes) == 0:
        return pd.DataFrame()

    if len(dataframes) == 1:
        result = dataframes[0]
        # Return Series if all inputs were Series
        if all_series and len(result.columns) == 1:
            return result.iloc[:, 0].rename(series_name)
        return result

    # Start with the last (newest/primary) dataframe
    result = dataframes[-1].copy()
    df_cols = result.columns.tolist()

    # Process in reverse order: from second-to-last back to first
    for i in range(len(dataframes) - 2, -1, -1):
        prev_df = dataframes[i]

        # Get the earliest date in current result
        earliest_date = result.index.min()

        # Filter previous dataframe to get rows before the earliest date
        historical_rows = prev_df[prev_df.index < earliest_date].copy()

        # Align columns - handle column name differences
        if len(historical_rows.columns) == len(df_cols):
            historical_rows.columns = df_cols
        else:
            # Select only matching columns or first N columns
            historical_rows = historical_rows.iloc[:, : len(df_cols)]
            historical_rows.columns = df_cols

        if not historical_rows.empty:
            # Prepend historical rows to result
            result = pd.concat([historical_rows, result], axis=0)

    # Sort by index to ensure chronological order
    result = result.sort_index()

    # Remove any duplicate indices, keeping the last (newest) value
    result = result[~result.index.duplicated(keep="last")]

    # Return Series if all inputs were Series
    if all_series and len(result.columns) == 1:
        return result.iloc[:, 0].rename(series_name)

    return result


@register_op("TS_RANK", category="Time Series")
def ts_rank_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling percentile rank within window.

    Ranks the current value as a percentile of the past N values.
    Returns values in [0, 1] where 1 = highest in window.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        TS_RANK($returns, 252)  # Rank within trailing year
    """

    def pct_rank(x: "pd.Series") -> float:
        """Calculate percentile rank of last value in series."""
        if len(x) == 0 or x.isna().all():
            return float("nan")
        # Rank of last value as percentile
        rank = (x < x.iloc[-1]).sum()
        return rank / (len(x) - 1) if len(x) > 1 else 0.5

    return data.rolling(window=window).apply(pct_rank, raw=False)


@register_op("TS_ZSCORE", category="Time Series")
def ts_zscore_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling Z-score within window.

    Z-score = (x - mean) / std over trailing window.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        TS_ZSCORE($returns, 20)  # Z-score within trailing month
    """
    rolling = data.rolling(window=window)
    mean = rolling.mean()
    std = rolling.std()
    return (data - mean) / std


@register_op("TS_SUM", category="Time Series")
def ts_sum_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling sum over window.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        TS_SUM($volume, 20)  # 20-day volume sum
    """
    return data.rolling(window=window).sum()


@register_op("TS_PRODUCT", category="Time Series")
def ts_product_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling product over window.

    Useful for compound returns.

    Args:
        data: Series or DataFrame (typically 1 + returns)
        window: Rolling window size

    Example:
        TS_PRODUCT(1 + $returns, 20) - 1  # 20-day compound return
    """
    import numpy as np

    def _product(x: "pd.Series") -> float:
        return np.prod(x)

    return data.rolling(window=window).apply(_product, raw=True)


@register_op("TS_ARGMAX", category="Time Series")
def ts_argmax_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Position of maximum value within window (0 = oldest, window-1 = newest).

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        TS_ARGMAX($close, 20)  # Where was high in last 20 days?
    """
    import numpy as np

    return data.rolling(window=window).apply(np.argmax, raw=True)


@register_op("TS_ARGMIN", category="Time Series")
def ts_argmin_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Position of minimum value within window (0 = oldest, window-1 = newest).

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        TS_ARGMIN($close, 20)  # Where was low in last 20 days?
    """
    import numpy as np

    return data.rolling(window=window).apply(np.argmin, raw=True)


@register_op("DECAY_LINEAR", category="Time Series")
def decay_linear_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Linear decay weighted average.

    Weights: [1, 2, 3, ..., window] normalized.
    More recent values get higher weight.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        DECAY_LINEAR($returns, 20)  # Recency-weighted average
    """
    import numpy as np

    weights = np.arange(1, window + 1, dtype=float)
    weights = weights / weights.sum()

    def weighted_avg(x: "pd.Series") -> float:
        return np.dot(x, weights)

    return data.rolling(window=window).apply(weighted_avg, raw=True)


@register_op("DECAY_EXP", category="Time Series")
def decay_exp_op(
    data: "pd.Series | pd.DataFrame",
    halflife: int,
) -> "pd.Series | pd.DataFrame":
    """Exponential decay weighted average (EWMA).

    Uses exponential moving average with given halflife.

    Args:
        data: Series or DataFrame
        halflife: Halflife for exponential decay

    Example:
        DECAY_EXP($returns, 10)  # Exponentially weighted average
    """
    return data.ewm(halflife=halflife).mean()
