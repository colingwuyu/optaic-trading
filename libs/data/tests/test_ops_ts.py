"""Tests for Time Series Operators (ts.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.data.ops import OPS_REGISTRY


class TestTsConcat:
    """Tests for TS_CONCAT operator."""

    def test_concat_two_series(self):
        """Test concatenating two non-overlapping series."""
        ts_concat = OPS_REGISTRY.get("TS_CONCAT")

        s1 = pd.Series([1, 2, 3], index=pd.date_range("2024-01-01", periods=3))
        s2 = pd.Series([4, 5, 6], index=pd.date_range("2024-01-04", periods=3))

        result = ts_concat(s1, s2)

        assert len(result) == 6
        assert result.iloc[0] == 1
        assert result.iloc[-1] == 6

    def test_concat_overlapping_series(self):
        """Test concatenating overlapping series (later takes precedence)."""
        ts_concat = OPS_REGISTRY.get("TS_CONCAT")

        s1 = pd.Series([1, 2, 3], index=pd.date_range("2024-01-01", periods=3))
        s2 = pd.Series([20, 30, 40], index=pd.date_range("2024-01-02", periods=3))

        result = ts_concat(s1, s2)

        # s2 should overwrite overlapping values
        assert result.loc["2024-01-01"] == 1  # From s1 (no overlap)
        assert result.loc["2024-01-02"] == 20  # From s2 (overwrites)
        assert result.loc["2024-01-03"] == 30  # From s2

    def test_concat_dataframes(self):
        """Test concatenating DataFrames."""
        ts_concat = OPS_REGISTRY.get("TS_CONCAT")

        df1 = pd.DataFrame(
            {"a": [1, 2], "b": [10, 20]},
            index=pd.date_range("2024-01-01", periods=2),
        )
        df2 = pd.DataFrame(
            {"a": [3, 4], "b": [30, 40]},
            index=pd.date_range("2024-01-03", periods=2),
        )

        result = ts_concat(df1, df2)

        assert len(result) == 4
        assert list(result.columns) == ["a", "b"]

    def test_concat_single_input(self):
        """Test with single input returns as-is."""
        ts_concat = OPS_REGISTRY.get("TS_CONCAT")

        s1 = pd.Series([1, 2, 3], index=pd.date_range("2024-01-01", periods=3))
        result = ts_concat(s1)

        pd.testing.assert_series_equal(result, s1)


class TestTsRank:
    """Tests for TS_RANK operator."""

    def test_ts_rank_basic(self):
        """Test basic percentile ranking."""
        ts_rank = OPS_REGISTRY.get("TS_RANK")

        data = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        result = ts_rank(data, window=5)

        # Last value in each window should be ranked
        assert len(result) == 10
        # First 4 values should be NaN (not enough window)
        assert result.iloc[:4].isna().all()
        # Later values should be between 0 and 1
        assert (result.iloc[4:] >= 0).all()
        assert (result.iloc[4:] <= 1).all()

    def test_ts_rank_with_dataframe(self):
        """Test ranking with DataFrame."""
        ts_rank = OPS_REGISTRY.get("TS_RANK")

        df = pd.DataFrame(
            {"a": range(10), "b": range(10, 20)},
            index=pd.date_range("2024-01-01", periods=10),
        )
        result = ts_rank(df, window=5)

        assert result.shape == df.shape
        assert list(result.columns) == ["a", "b"]


class TestTsZscore:
    """Tests for TS_ZSCORE operator."""

    def test_ts_zscore_basic(self):
        """Test z-score calculation."""
        ts_zscore = OPS_REGISTRY.get("TS_ZSCORE")

        # Create data with known mean and std
        data = pd.Series([100, 100, 100, 100, 200])
        result = ts_zscore(data, window=5)

        # Last value should have positive z-score (above mean)
        assert result.iloc[-1] > 0

    def test_ts_zscore_constant_series(self):
        """Test z-score with constant values."""
        ts_zscore = OPS_REGISTRY.get("TS_ZSCORE")

        data = pd.Series([100] * 10)
        result = ts_zscore(data, window=5)

        # Z-score of constant series should be 0 (or NaN due to zero std)
        # Implementation may vary - check that it doesn't crash
        assert len(result) == 10


class TestTsSum:
    """Tests for TS_SUM operator."""

    def test_ts_sum_basic(self):
        """Test rolling sum."""
        ts_sum = OPS_REGISTRY.get("TS_SUM")

        data = pd.Series([1, 2, 3, 4, 5])
        result = ts_sum(data, window=3)

        assert result.iloc[-1] == 12  # 3 + 4 + 5
        assert result.iloc[-2] == 9  # 2 + 3 + 4

    def test_ts_sum_dataframe(self):
        """Test rolling sum on DataFrame."""
        ts_sum = OPS_REGISTRY.get("TS_SUM")

        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]})
        result = ts_sum(df, window=3)

        assert result["a"].iloc[-1] == 12
        assert result["b"].iloc[-1] == 120


class TestTsProduct:
    """Tests for TS_PRODUCT operator."""

    def test_ts_product_basic(self):
        """Test rolling product."""
        ts_product = OPS_REGISTRY.get("TS_PRODUCT")

        data = pd.Series([1, 2, 3, 4, 5])
        result = ts_product(data, window=3)

        assert result.iloc[-1] == 60  # 3 * 4 * 5
        assert result.iloc[-2] == 24  # 2 * 3 * 4


class TestTsArgmax:
    """Tests for TS_ARGMAX operator."""

    def test_ts_argmax_basic(self):
        """Test rolling argmax (position of max value)."""
        ts_argmax = OPS_REGISTRY.get("TS_ARGMAX")

        data = pd.Series([1, 5, 3, 4, 2])
        result = ts_argmax(data, window=3)

        # In window [3,4,2], max is 4 at position 1
        assert result.iloc[-1] == 1  # Position of 4 in [3,4,2]


class TestTsArgmin:
    """Tests for TS_ARGMIN operator."""

    def test_ts_argmin_basic(self):
        """Test rolling argmin (position of min value)."""
        ts_argmin = OPS_REGISTRY.get("TS_ARGMIN")

        data = pd.Series([5, 1, 3, 4, 2])
        result = ts_argmin(data, window=3)

        # In window [3,4,2], min is 2 at position 2
        assert result.iloc[-1] == 2  # Position of 2 in [3,4,2]


class TestDecayLinear:
    """Tests for DECAY_LINEAR operator."""

    def test_decay_linear_basic(self):
        """Test linear decay weighted average."""
        decay_linear = OPS_REGISTRY.get("DECAY_LINEAR")

        data = pd.Series([1, 2, 3, 4, 5])
        result = decay_linear(data, window=3)

        # Weights: [1, 2, 3] / 6 = [1/6, 2/6, 3/6]
        # For last window [3, 4, 5]: 3*1/6 + 4*2/6 + 5*3/6 = (3 + 8 + 15)/6 = 26/6 ≈ 4.33
        assert len(result) == 5
        assert not np.isnan(result.iloc[-1])

    def test_decay_linear_more_weight_on_recent(self):
        """Test that recent values have more weight."""
        decay_linear = OPS_REGISTRY.get("DECAY_LINEAR")

        # Data where recent values are high
        data = pd.Series([1, 1, 1, 1, 100])
        result = decay_linear(data, window=5)

        # Result should be pulled toward 100 but weights are [1,2,3,4,5]/15
        # = (1+2+3+4+500)/15 = 510/15 = 34
        # Simple mean would be (1+1+1+1+100)/5 = 20.8
        # So result should be > simple mean (more weight on recent)
        assert result.iloc[-1] > 20  # Better than simple mean


class TestDecayExp:
    """Tests for DECAY_EXP operator."""

    def test_decay_exp_basic(self):
        """Test exponential decay (EMA)."""
        decay_exp = OPS_REGISTRY.get("DECAY_EXP")

        data = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        result = decay_exp(data, halflife=5)

        # EMA should be smoother than raw data
        assert len(result) == 10
        # EMA of increasing series should be below the raw values
        assert result.iloc[-1] < 10

    def test_decay_exp_more_weight_on_recent(self):
        """Test that recent values have more weight in EMA."""
        decay_exp = OPS_REGISTRY.get("DECAY_EXP")

        data = pd.Series([1, 1, 1, 1, 100])
        result = decay_exp(data, halflife=3)

        # EMA should be pulled toward 100
        assert result.iloc[-1] > 10


class TestOperatorsRegistered:
    """Test that all TS operators are registered."""

    @pytest.mark.parametrize(
        "op_name",
        [
            "TS_CONCAT",
            "TS_RANK",
            "TS_ZSCORE",
            "TS_SUM",
            "TS_PRODUCT",
            "TS_ARGMAX",
            "TS_ARGMIN",
            "DECAY_LINEAR",
            "DECAY_EXP",
        ],
    )
    def test_operator_registered(self, op_name):
        """Test that operator is in registry."""
        assert op_name in OPS_REGISTRY
        op_func = OPS_REGISTRY.get(op_name)
        assert callable(op_func)
