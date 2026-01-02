"""Tests for Futures Operators (futures.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from libs.data.ops import OPS_REGISTRY


class TestFuturesUniverse:
    """Tests for FUTURES_UNIVERSE operator."""

    def test_futures_universe_returns_list(self):
        """Test that FUTURES_UNIVERSE returns a list."""
        futures_universe = OPS_REGISTRY.get("FUTURES_UNIVERSE")
        result = futures_universe()

        assert isinstance(result, list)
        # May be empty if no config file exists
        assert isinstance(result, list)

    def test_futures_universe_registered(self):
        """Test that operator is registered."""
        assert "FUTURES_UNIVERSE" in OPS_REGISTRY


class TestRollFutures:
    """Tests for ROLL_FUTURES operator."""

    @pytest.fixture
    def sample_futures_data(self):
        """Create sample futures data for testing."""
        dates = pd.date_range("2024-01-01", periods=30, freq="B")

        # Price table with generic contracts
        price_table = pd.DataFrame(
            {
                "ES1 Index": [4500 + i for i in range(30)],
                "ES2 Index": [4510 + i for i in range(30)],
                "NQ1 Index": [15000 + i * 2 for i in range(30)],
                "NQ2 Index": [15020 + i * 2 for i in range(30)],
            },
            index=dates,
        )

        # Active contract info
        active_contract = pd.DataFrame(
            {
                "ES1 Index": ["ESH4 Index"] * 15 + ["ESM4 Index"] * 15,
                "NQ1 Index": ["NQH4 Index"] * 15 + ["NQM4 Index"] * 15,
            },
            index=dates,
        )

        # Date table with contract expiries
        date_table = pd.DataFrame(
            {
                "TICKER": [
                    "ESH4 Index",
                    "ESM4 Index",
                    "NQH4 Index",
                    "NQM4 Index",
                ],
                "FUT_NOTICE_FIRST": pd.to_datetime(
                    ["2024-03-01", "2024-06-01", "2024-03-01", "2024-06-01"]
                ),
                "LAST_TRADEABLE_DT": pd.to_datetime(
                    ["2024-03-15", "2024-06-15", "2024-03-15", "2024-06-15"]
                ),
            }
        )

        return price_table, active_contract, date_table

    def test_roll_futures_registered(self):
        """Test that operator is registered."""
        assert "ROLL_FUTURES" in OPS_REGISTRY
        assert "ROLL_FUTURES_SINGLE" in OPS_REGISTRY

    def test_roll_futures_returns_dataframe(self, sample_futures_data):
        """Test that ROLL_FUTURES returns a DataFrame."""
        roll_futures = OPS_REGISTRY.get("ROLL_FUTURES")
        price_table, active_contract, date_table = sample_futures_data

        # This will likely return empty without proper config
        result = roll_futures(price_table, active_contract, date_table)

        assert isinstance(result, pd.DataFrame)
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_roll_futures_single_returns_series(self, sample_futures_data):
        """Test that ROLL_FUTURES_SINGLE returns a Series."""
        roll_futures_single = OPS_REGISTRY.get("ROLL_FUTURES_SINGLE")
        price_table, active_contract, date_table = sample_futures_data

        # This will likely return empty without proper config
        result = roll_futures_single(
            price_table, active_contract, date_table, ticker="ES Index"
        )

        assert isinstance(result, pd.Series)


class TestFuturesOperatorsExist:
    """Test that all futures operators exist in registry."""

    @pytest.mark.parametrize(
        "op_name",
        ["ROLL_FUTURES", "ROLL_FUTURES_SINGLE", "FUTURES_UNIVERSE"],
    )
    def test_operator_exists(self, op_name):
        """Test operator is in registry."""
        assert op_name in OPS_REGISTRY
        op_func = OPS_REGISTRY.get(op_name)
        assert callable(op_func)
