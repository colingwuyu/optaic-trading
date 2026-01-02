"""Test fixtures for libs/data tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def clear_virtual_store_cache():
    """Clear VirtualStore cache before and after each test.

    VirtualStore uses a class-level cache keyed by resource_id.
    This can cause test pollution if multiple tests use the same resource_id.
    """
    from libs.data.store.virtual import VirtualStore

    VirtualStore._cache.clear()
    yield
    VirtualStore._cache.clear()


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for store tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_timeseries_df():
    """Create a sample time series DataFrame."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "close": [100 + i * 0.5 + (i % 10) for i in range(100)],
            "volume": [1000000 + i * 1000 for i in range(100)],
        }
    )


@pytest.fixture
def sample_pit_df():
    """Create a sample point-in-time DataFrame with knowledge_date."""
    # Simulates GDP revisions - same observation date with different release dates
    data = []
    for obs_date in pd.date_range("2024-01-01", periods=4, freq="ME"):
        # Initial estimate
        data.append(
            {
                "date": obs_date,
                "knowledge_date": obs_date + pd.Timedelta(days=30),
                "value": 100 + len(data),
            }
        )
        # Revised estimate
        data.append(
            {
                "date": obs_date,
                "knowledge_date": obs_date + pd.Timedelta(days=60),
                "value": 100.5 + len(data),
            }
        )

    return pd.DataFrame(data)


@pytest.fixture
def sample_expression_context(sample_timeseries_df):
    """Create a context dict for expression testing."""
    df = sample_timeseries_df.set_index("date")
    return {
        "prices": df,
        "close": df["close"],
        "volume": df["volume"],
    }
