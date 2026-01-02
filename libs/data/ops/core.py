"""Core Operator Definitions.

Standard operators for expression evaluation.
Adapted from optaic-v0/function/ops.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

# Global operator registry (dict of name -> function)
OPS_REGISTRY: dict[str, Callable] = {}


def register_op(name: str, category: str = "Math"):
    """Decorator to register an operator function.

    Args:
        name: Operator name (will be uppercased)
        category: Category for documentation/UI grouping

    Example:
        @register_op("MEAN", category="Statistics")
        def mean_op(data, window):
            return data.rolling(window=window).mean()
    """

    def decorator(func: Callable) -> Callable:
        func.category = category  # type: ignore
        OPS_REGISTRY[name.upper()] = func
        return func

    return decorator


def _validate_numeric(
    series: "pd.Series | pd.DataFrame",
    op_name: str,
) -> None:
    """Runtime check for numeric types."""
    import pandas as pd

    if isinstance(series, pd.Series):
        if not pd.api.types.is_numeric_dtype(series):
            raise TypeError(
                f"Operator '{op_name}' requires numeric input, got {series.dtype}"
            )
    elif isinstance(series, pd.DataFrame):
        for col in series.columns:
            if not pd.api.types.is_numeric_dtype(series[col]):
                raise TypeError(
                    f"Operator '{op_name}' requires numeric input. "
                    f"Column '{col}' is {series[col].dtype}"
                )


# =============================================================================
# Time Series Operators
# =============================================================================


@register_op("REF", category="Time Series")
def ref_op(
    data: "pd.Series | pd.DataFrame",
    n: int = 1,
) -> "pd.Series | pd.DataFrame":
    """Shift data by N periods.

    Positive N = Lag (lookback into past)
    Negative N = Lead (forward/future)

    Args:
        data: Series or DataFrame to shift
        n: Number of periods (default: 1)

    Example:
        REF($close, 1)  # Yesterday's close
        REF($close, -1) # Tomorrow's close (for target creation)
    """
    return data.shift(n)


@register_op("DELTA", category="Time Series")
def delta_op(
    data: "pd.Series | pd.DataFrame",
    n: int = 1,
) -> "pd.Series | pd.DataFrame":
    """Difference between current and N periods ago.

    Args:
        data: Series or DataFrame
        n: Number of periods (default: 1)

    Example:
        DELTA($close, 1)  # Daily change
        DELTA($close, 5)  # 5-day change
    """
    _validate_numeric(data, "DELTA")
    return data.diff(n)


# =============================================================================
# Statistics Operators
# =============================================================================


@register_op("MEAN", category="Statistics")
def mean_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling mean (moving average).

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        MEAN($close, 20)  # 20-day moving average
    """
    _validate_numeric(data, "MEAN")
    return data.rolling(window=window).mean()


@register_op("STD", category="Statistics")
def std_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling standard deviation.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        STD($returns, 20)  # 20-day volatility
    """
    _validate_numeric(data, "STD")
    return data.rolling(window=window).std()


@register_op("CORR", category="Statistics")
def corr_op(
    data_x: "pd.Series",
    data_y: "pd.Series",
    window: int,
) -> "pd.Series":
    """Rolling correlation between two series.

    Args:
        data_x: First series
        data_y: Second series
        window: Rolling window size

    Example:
        CORR($stock_returns, $market_returns, 60)
    """
    _validate_numeric(data_x, "CORR")
    _validate_numeric(data_y, "CORR")
    return data_x.rolling(window=window).corr(data_y)


@register_op("BETA", category="Statistics")
def beta_op(
    data_y: "pd.Series",
    data_x: "pd.Series",
    window: int,
) -> "pd.Series":
    """Rolling beta (Cov(y, x) / Var(x)).

    Args:
        data_y: Dependent variable (e.g., stock returns)
        data_x: Independent variable (e.g., market returns)
        window: Rolling window size

    Example:
        BETA($stock_returns, $market_returns, 60)
    """
    _validate_numeric(data_y, "BETA")
    _validate_numeric(data_x, "BETA")
    cov = data_y.rolling(window=window).cov(data_x)
    var = data_x.rolling(window=window).var()
    return cov / var


@register_op("MAX", category="Statistics")
def max_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling maximum.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        MAX($high, 52 * 5)  # 52-week high (assuming daily data)
    """
    _validate_numeric(data, "MAX")
    return data.rolling(window=window).max()


@register_op("MIN", category="Statistics")
def min_op(
    data: "pd.Series | pd.DataFrame",
    window: int,
) -> "pd.Series | pd.DataFrame":
    """Rolling minimum.

    Args:
        data: Series or DataFrame
        window: Rolling window size

    Example:
        MIN($low, 52 * 5)  # 52-week low
    """
    _validate_numeric(data, "MIN")
    return data.rolling(window=window).min()


# =============================================================================
# Math Operators
# =============================================================================


@register_op("LOG", category="Math")
def log_op(data: "pd.Series | pd.DataFrame") -> "pd.Series | pd.DataFrame":
    """Natural logarithm.

    Example:
        LOG($price)  # Log price
    """
    import numpy as np

    _validate_numeric(data, "LOG")
    return np.log(data)


@register_op("ABS", category="Math")
def abs_op(data: "pd.Series | pd.DataFrame") -> "pd.Series | pd.DataFrame":
    """Absolute value.

    Example:
        ABS($returns)  # Absolute returns
        |$returns|     # Same (shorthand syntax)
    """
    _validate_numeric(data, "ABS")
    return data.abs()


@register_op("SIGN", category="Math")
def sign_op(data: "pd.Series | pd.DataFrame") -> "pd.Series | pd.DataFrame":
    """Sign of values (-1, 0, or 1).

    Example:
        SIGN($returns)  # Direction of returns
    """
    import numpy as np

    _validate_numeric(data, "SIGN")
    return np.sign(data)


@register_op("ADD", category="Math")
def add_op(a: Any, b: Any) -> Any:
    """Addition. Equivalent to a + b."""
    return a + b


@register_op("SUB", category="Math")
def sub_op(a: Any, b: Any) -> Any:
    """Subtraction. Equivalent to a - b."""
    return a - b


@register_op("MUL", category="Math")
def mul_op(a: Any, b: Any) -> Any:
    """Multiplication. Equivalent to a * b."""
    return a * b


@register_op("DIV", category="Math")
def div_op(a: Any, b: Any) -> Any:
    """Division. Equivalent to a / b."""
    return a / b


@register_op("CUMRET", category="Math")
def cumret_op(
    returns: "pd.Series | pd.DataFrame",
) -> "pd.Series | pd.DataFrame":
    """Cumulative return (price index from returns).

    Computes: cumprod(1 + returns)

    Example:
        CUMRET($daily_returns)  # Price index from returns
    """
    _validate_numeric(returns, "CUMRET")
    return (1 + returns.fillna(0)).cumprod()


@register_op("COMBINE", category="Math")
def combine_op(*args: "pd.Series | pd.DataFrame") -> "pd.DataFrame":
    """Combine multiple Series/DataFrames column-wise.

    Example:
        COMBINE($ma_fast, $ma_slow)  # Two moving averages side by side
    """
    import pandas as pd

    valid_objs = [obj for obj in args if obj is not None]
    if not valid_objs:
        return pd.DataFrame()

    dfs = []
    for i, obj in enumerate(valid_objs):
        if isinstance(obj, pd.Series):
            name = obj.name if obj.name else f"col_{i}"
            dfs.append(obj.to_frame(name=name))
        elif isinstance(obj, pd.DataFrame):
            dfs.append(obj)

    return pd.concat(dfs, axis=1)


# =============================================================================
# PIT (Point-in-Time) Operators
# =============================================================================


@register_op("VALUES", category="PIT")
def values_op(
    data: "pd.DataFrame",
    col: str = "value",
) -> "pd.Series":
    """Extract value column from PIT dataset.

    Drops metadata columns like release_date, keeping just the values.

    Example:
        VALUES($gdp_vintage)  # Just the GDP values
    """
    import numpy as np
    import pandas as pd

    if isinstance(data, pd.Series):
        return data
    if col in data.columns:
        return data[col]
    # If only one numeric column, return that
    numeric_cols = data.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) == 1:
        return data[numeric_cols[0]]
    raise ValueError(f"Column '{col}' not found. Available: {list(data.columns)}")


@register_op("DROP_META", category="PIT")
def drop_meta_op(
    data: "pd.DataFrame",
    meta_cols: list[str] | None = None,
) -> "pd.DataFrame":
    """Drop metadata columns (like release_date).

    Example:
        DROP_META($vintage_data)
    """
    import pandas as pd

    if isinstance(data, pd.Series):
        return data.to_frame()

    if meta_cols is None:
        meta_cols = ["release_date", "realtime_start", "realtime_end", "knowledge_date"]

    cols_to_drop = [c for c in meta_cols if c in data.columns]
    return data.drop(columns=cols_to_drop, errors="ignore")


@register_op("AS_OF_DATE", category="PIT")
def as_of_date_op(
    data: "pd.DataFrame",
    as_of: str,
) -> "pd.DataFrame":
    """Filter PIT data to what was known as of a specific date.

    For each observation date, returns the latest release before as_of.

    Example:
        AS_OF_DATE($gdp_vintage, "2020-01-01")
    """
    import pandas as pd

    if not isinstance(data.index, pd.MultiIndex):
        # If single index, check for knowledge_date column
        if "knowledge_date" in data.columns:
            as_of_ts = pd.Timestamp(as_of)
            return data[pd.to_datetime(data["knowledge_date"]) <= as_of_ts]
        return data

    as_of_ts = pd.Timestamp(as_of)

    # Reset to filter on release_date
    df = data.reset_index()
    release_col = data.index.names[1]  # Usually "release_date"
    obs_col = data.index.names[0]  # Usually "obs_date"

    # Filter to releases before as_of
    df = df[df[release_col] <= as_of_ts]

    # For each obs_date, take the latest release
    df = df.sort_values([obs_col, release_col])
    df = df.groupby(obs_col).last()

    return df
