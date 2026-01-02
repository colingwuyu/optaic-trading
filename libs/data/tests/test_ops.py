"""Tests for operator implementations."""

import numpy as np
import pandas as pd
import pytest

from libs.data.ops import OPS_REGISTRY
from libs.data.ops.core import (
    abs_op,
    add_op,
    beta_op,
    combine_op,
    corr_op,
    cumret_op,
    delta_op,
    div_op,
    log_op,
    max_op,
    mean_op,
    min_op,
    mul_op,
    ref_op,
    sign_op,
    std_op,
    sub_op,
    values_op,
)


@pytest.fixture
def sample_series():
    """Create a sample series for testing."""
    return pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], name="value")


@pytest.fixture
def sample_df():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )


class TestOpsRegistry:
    """Tests for operator registry."""

    def test_registry_contains_core_ops(self):
        """Test that core operators are registered."""
        expected_ops = [
            "REF",
            "DELTA",
            "MEAN",
            "STD",
            "MAX",
            "MIN",
            "LOG",
            "ABS",
            "SIGN",
            "ADD",
            "SUB",
            "MUL",
            "DIV",
            "CUMRET",
            "COMBINE",
        ]
        for op in expected_ops:
            assert op in OPS_REGISTRY, f"{op} not in registry"


class TestTimeSeriesOps:
    """Tests for time series operators."""

    def test_ref_positive_shift(self, sample_series):
        """Test REF with positive shift (lag)."""
        result = ref_op(sample_series, 1)
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == 1.0
        assert result.iloc[2] == 2.0

    def test_ref_negative_shift(self, sample_series):
        """Test REF with negative shift (lead)."""
        result = ref_op(sample_series, -1)
        assert result.iloc[0] == 2.0
        assert result.iloc[1] == 3.0
        assert pd.isna(result.iloc[-1])

    def test_delta(self, sample_series):
        """Test DELTA operator."""
        result = delta_op(sample_series, 1)
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == 1.0  # 2 - 1
        assert result.iloc[2] == 1.0  # 3 - 2


class TestStatisticsOps:
    """Tests for statistics operators."""

    def test_mean(self, sample_series):
        """Test MEAN (rolling average)."""
        result = mean_op(sample_series, 3)
        # First 2 values are NaN (not enough data)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        # Third value: mean of [1, 2, 3] = 2
        assert result.iloc[2] == 2.0

    def test_std(self, sample_series):
        """Test STD (rolling standard deviation)."""
        result = std_op(sample_series, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        # Third value: std of [1, 2, 3]
        assert result.iloc[2] == pytest.approx(1.0, rel=0.01)

    def test_max(self, sample_series):
        """Test MAX (rolling maximum)."""
        result = max_op(sample_series, 3)
        assert result.iloc[2] == 3.0
        assert result.iloc[3] == 4.0

    def test_min(self, sample_series):
        """Test MIN (rolling minimum)."""
        result = min_op(sample_series, 3)
        assert result.iloc[2] == 1.0
        assert result.iloc[3] == 2.0

    def test_corr(self, sample_df):
        """Test CORR (rolling correlation)."""
        result = corr_op(sample_df["a"], sample_df["b"], 3)
        # a and b are perfectly negatively correlated
        assert result.iloc[2] == pytest.approx(-1.0, rel=0.01)

    def test_beta(self):
        """Test BETA (rolling regression coefficient)."""
        # Create perfectly correlated series
        x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        y = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0])  # y = 2x
        result = beta_op(y, x, 3)
        # Beta should be 2.0
        assert result.iloc[2] == pytest.approx(2.0, rel=0.01)


class TestMathOps:
    """Tests for math operators."""

    def test_log(self, sample_series):
        """Test LOG operator."""
        result = log_op(sample_series)
        assert result.iloc[0] == 0.0  # log(1) = 0
        assert result.iloc[1] == pytest.approx(np.log(2), rel=0.01)

    def test_abs(self):
        """Test ABS operator."""
        series = pd.Series([-1, 0, 1])
        result = abs_op(series)
        assert list(result) == [1, 0, 1]

    def test_sign(self):
        """Test SIGN operator."""
        series = pd.Series([-5, 0, 5])
        result = sign_op(series)
        assert list(result) == [-1, 0, 1]

    def test_add(self, sample_series):
        """Test ADD operator."""
        result = add_op(sample_series, 10)
        assert result.iloc[0] == 11.0

    def test_sub(self, sample_series):
        """Test SUB operator."""
        result = sub_op(sample_series, 1)
        assert result.iloc[0] == 0.0

    def test_mul(self, sample_series):
        """Test MUL operator."""
        result = mul_op(sample_series, 2)
        assert result.iloc[0] == 2.0
        assert result.iloc[1] == 4.0

    def test_div(self, sample_series):
        """Test DIV operator."""
        result = div_op(sample_series, 2)
        assert result.iloc[0] == 0.5
        assert result.iloc[1] == 1.0

    def test_cumret(self):
        """Test CUMRET (cumulative returns)."""
        returns = pd.Series([0.1, 0.1, -0.1])  # 10%, 10%, -10%
        result = cumret_op(returns)
        assert result.iloc[0] == pytest.approx(1.1, rel=0.01)
        assert result.iloc[1] == pytest.approx(1.21, rel=0.01)
        assert result.iloc[2] == pytest.approx(1.089, rel=0.01)

    def test_combine(self, sample_df):
        """Test COMBINE operator."""
        series_a = sample_df["a"]
        series_b = sample_df["b"]
        result = combine_op(series_a, series_b)
        assert isinstance(result, pd.DataFrame)
        assert len(result.columns) == 2


class TestPITOps:
    """Tests for PIT (point-in-time) operators."""

    def test_values_with_value_column(self):
        """Test VALUES extracts value column."""
        df = pd.DataFrame(
            {
                "value": [1, 2, 3],
                "release_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            }
        )
        result = values_op(df)
        assert isinstance(result, pd.Series)
        assert list(result) == [1, 2, 3]

    def test_values_with_series(self):
        """Test VALUES returns series as-is."""
        series = pd.Series([1, 2, 3])
        result = values_op(series)
        assert list(result) == [1, 2, 3]

    def test_values_single_numeric_column(self):
        """Test VALUES finds single numeric column."""
        df = pd.DataFrame(
            {
                "obs_date": ["2024-01-01", "2024-01-02"],
                "numeric_val": [100, 200],
            }
        )
        result = values_op(df)
        assert list(result) == [100, 200]


class TestOperatorTypeValidation:
    """Tests for operator type validation."""

    def test_delta_requires_numeric(self):
        """Test DELTA raises on non-numeric input."""
        string_series = pd.Series(["a", "b", "c"])
        with pytest.raises(TypeError, match="numeric"):
            delta_op(string_series, 1)

    def test_mean_requires_numeric(self):
        """Test MEAN raises on non-numeric input."""
        string_series = pd.Series(["a", "b", "c"])
        with pytest.raises(TypeError, match="numeric"):
            mean_op(string_series, 2)

    def test_log_requires_numeric(self):
        """Test LOG raises on non-numeric input."""
        string_series = pd.Series(["a", "b", "c"])
        with pytest.raises(TypeError, match="numeric"):
            log_op(string_series)
