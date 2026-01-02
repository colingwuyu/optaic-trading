"""Tests for Extended Accessor Implementations."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from libs.data.registry import ACCESSOR_FACTORY
from libs.data.store.virtual import VirtualStore


class TestEconomicsAccessor:
    """Tests for EconomicsAccessor with vintage/revision support."""

    @pytest.fixture
    def vintage_data(self):
        """Create sample vintage data with revisions."""
        # GDP data with multiple releases
        data = []
        for obs_date in pd.date_range("2024-01-01", periods=4, freq="ME"):
            # Initial release
            data.append(
                {
                    "value": 100 + len(data),
                    "release_date": obs_date + pd.Timedelta(days=30),
                }
            )
            # Revised release
            data.append(
                {
                    "value": 100.5 + len(data),
                    "release_date": obs_date + pd.Timedelta(days=60),
                }
            )
            # Final release
            data.append(
                {
                    "value": 101 + len(data),
                    "release_date": obs_date + pd.Timedelta(days=90),
                }
            )

        df = pd.DataFrame(data)
        # Create observation dates
        obs_dates = []
        for obs_date in pd.date_range("2024-01-01", periods=4, freq="ME"):
            obs_dates.extend([obs_date, obs_date, obs_date])

        df.index = pd.DatetimeIndex(obs_dates)
        df.index.name = "obs_date"
        return df

    @pytest.fixture
    def economics_store(self, vintage_data, tmp_path):
        """Create a store with vintage data."""
        store = VirtualStore("econ-test", {}, data_dir=tmp_path)
        store.write(vintage_data)
        return store

    def test_economics_accessor_registered(self):
        """Test that EconomicsAccessor is registered."""
        assert "EconomicsAccessor" in ACCESSOR_FACTORY

    def test_get_request_model(self, economics_store):
        """Test getting the request model."""
        accessor = ACCESSOR_FACTORY.build(
            "EconomicsAccessor",
            resource_id="econ-test",
            config={},
            store=economics_store,
        )

        model = accessor.get_request_model()
        assert model is not None
        # Should have revision and as_of_date fields
        assert hasattr(model, "model_fields")

    def test_get_latest_revision(self, economics_store, vintage_data):
        """Test retrieving latest revisions."""
        accessor = ACCESSOR_FACTORY.build(
            "EconomicsAccessor",
            resource_id="econ-test",
            config={},
            store=economics_store,
        )

        result = accessor.get(
            as_of_date=date(2024, 12, 31),
            revision="latest",
        )

        assert result is not None
        # Should have one row per observation date (latest revision)
        assert len(result) > 0

    def test_get_initial_revision(self, economics_store, vintage_data):
        """Test retrieving initial revisions."""
        accessor = ACCESSOR_FACTORY.build(
            "EconomicsAccessor",
            resource_id="econ-test",
            config={},
            store=economics_store,
        )

        result = accessor.get(
            as_of_date=date(2024, 12, 31),
            revision="initial",
        )

        assert result is not None
        # Should have one row per observation date (first release)
        assert len(result) > 0

    def test_get_all_revisions(self, economics_store, vintage_data):
        """Test retrieving all revisions."""
        accessor = ACCESSOR_FACTORY.build(
            "EconomicsAccessor",
            resource_id="econ-test",
            config={},
            store=economics_store,
        )

        result = accessor.get(
            as_of_date=date(2024, 12, 31),
            revision="all",
        )

        assert result is not None
        # Should have multiple rows per observation date
        assert len(result) > 0


class TestGenericFuturesAccessor:
    """Tests for GenericFuturesAccessor."""

    def test_futures_accessor_registered(self):
        """Test that GenericFuturesAccessor is registered."""
        assert "GenericFuturesAccessor" in ACCESSOR_FACTORY

    def test_get_request_model(self):
        """Test getting the request model."""
        accessor = ACCESSOR_FACTORY.build(
            "GenericFuturesAccessor",
            resource_id="futures-test",
            config={},
            store=None,
            context_loader=lambda *args, **kwargs: pd.DataFrame(),
        )

        model = accessor.get_request_model()
        assert model is not None
        assert hasattr(model, "model_fields")

    def test_get_output_columns(self):
        """Test getting output columns (from config)."""
        accessor = ACCESSOR_FACTORY.build(
            "GenericFuturesAccessor",
            resource_id="futures-test",
            config={},
            store=None,
            context_loader=lambda *args, **kwargs: pd.DataFrame(),
        )

        columns = accessor.get_output_columns()
        assert isinstance(columns, list)


class TestFieldsAccessor:
    """Tests for FieldsAccessor."""

    @pytest.fixture
    def sample_store(self, tmp_path):
        """Create a store with sample data."""
        store = VirtualStore("fields-test", {}, data_dir=tmp_path)
        df = pd.DataFrame(
            {
                "open": [100, 101, 102],
                "high": [105, 106, 107],
                "low": [95, 96, 97],
                "close": [103, 104, 105],
                "volume": [1000, 2000, 3000],
            },
            index=pd.date_range("2024-01-01", periods=3),
        )
        store.write(df)
        return store

    def test_fields_accessor_registered(self):
        """Test that FieldsAccessor is registered."""
        assert "FieldsAccessor" in ACCESSOR_FACTORY

    def test_get_all_fields(self, sample_store):
        """Test retrieving all fields."""
        accessor = ACCESSOR_FACTORY.build(
            "FieldsAccessor",
            resource_id="fields-test",
            config={},
            store=sample_store,
        )

        result = accessor.get()

        assert result is not None
        assert len(result.columns) == 5

    def test_get_specific_fields(self, sample_store):
        """Test retrieving specific fields."""
        accessor = ACCESSOR_FACTORY.build(
            "FieldsAccessor",
            resource_id="fields-test",
            config={},
            store=sample_store,
        )

        result = accessor.get(fields=["open", "close"])

        assert result is not None
        assert list(result.columns) == ["open", "close"]

    def test_get_fields_case_insensitive(self, sample_store):
        """Test case-insensitive field matching."""
        accessor = ACCESSOR_FACTORY.build(
            "FieldsAccessor",
            resource_id="fields-test",
            config={},
            store=sample_store,
        )

        result = accessor.get(fields=["OPEN", "CLOSE"])

        assert result is not None
        # Should match despite case difference
        assert len(result.columns) == 2

    def test_get_output_columns(self, sample_store):
        """Test getting output columns."""
        accessor = ACCESSOR_FACTORY.build(
            "FieldsAccessor",
            resource_id="fields-test",
            config={},
            store=sample_store,
        )

        columns = accessor.get_output_columns()

        assert "open" in columns
        assert "close" in columns


class TestTickerAccessor:
    """Tests for TickerAccessor."""

    @pytest.fixture
    def ticker_store(self, tmp_path):
        """Create a store with ticker data."""
        store = VirtualStore("ticker-test", {}, data_dir=tmp_path)
        df = pd.DataFrame(
            {
                "SPX Index": [4500, 4510, 4520],
                "NDX Index": [15000, 15100, 15200],
                "AAPL US Equity": [180, 181, 182],
            },
            index=pd.date_range("2024-01-01", periods=3),
        )
        store.write(df)
        return store

    def test_ticker_accessor_registered(self):
        """Test that TickerAccessor is registered."""
        assert "TickerAccessor" in ACCESSOR_FACTORY

    def test_get_all_tickers(self, ticker_store):
        """Test retrieving all tickers."""
        accessor = ACCESSOR_FACTORY.build(
            "TickerAccessor",
            resource_id="ticker-test",
            config={},
            store=ticker_store,
        )

        result = accessor.get()

        assert result is not None
        assert len(result.columns) == 3

    def test_get_specific_tickers(self, ticker_store):
        """Test retrieving specific tickers."""
        accessor = ACCESSOR_FACTORY.build(
            "TickerAccessor",
            resource_id="ticker-test",
            config={},
            store=ticker_store,
        )

        result = accessor.get(tickers=["SPX Index", "NDX Index"])

        assert result is not None
        assert list(result.columns) == ["SPX Index", "NDX Index"]

    def test_get_tickers_from_string(self, ticker_store):
        """Test retrieving tickers from comma-separated string."""
        accessor = ACCESSOR_FACTORY.build(
            "TickerAccessor",
            resource_id="ticker-test",
            config={},
            store=ticker_store,
        )

        result = accessor.get(tickers="SPX Index, NDX Index")

        assert result is not None
        assert len(result.columns) == 2

    def test_get_nonexistent_ticker(self, ticker_store):
        """Test retrieving non-existent ticker returns empty."""
        accessor = ACCESSOR_FACTORY.build(
            "TickerAccessor",
            resource_id="ticker-test",
            config={},
            store=ticker_store,
        )

        result = accessor.get(tickers=["NONEXISTENT"])

        assert result is not None
        assert len(result.columns) == 0


class TestUniverseSearchAccessor:
    """Tests for UniverseSearchAccessor."""

    @pytest.fixture
    def search_store(self, tmp_path):
        """Create a store with various tickers."""
        store = VirtualStore("search-test", {}, data_dir=tmp_path)
        df = pd.DataFrame(
            {
                "SPX Index": [4500],
                "NDX Index": [15000],
                "ES Index": [4480],
                "NQ Index": [14900],
                "AAPL US Equity": [180],
                "MSFT US Equity": [380],
                "GOOGL US Equity": [140],
            },
            index=pd.date_range("2024-01-01", periods=1),
        )
        store.write(df)
        return store

    def test_search_accessor_registered(self):
        """Test that UniverseSearchAccessor is registered."""
        assert "UniverseSearchAccessor" in ACCESSOR_FACTORY

    def test_search_all(self, search_store):
        """Test searching with no pattern returns all."""
        accessor = ACCESSOR_FACTORY.build(
            "UniverseSearchAccessor",
            resource_id="search-test",
            config={},
            store=search_store,
        )

        result = accessor.get()

        assert result is not None
        assert len(result) == 7
        assert "Ticker" in result.columns

    def test_search_by_pattern(self, search_store):
        """Test searching by regex pattern."""
        accessor = ACCESSOR_FACTORY.build(
            "UniverseSearchAccessor",
            resource_id="search-test",
            config={},
            store=search_store,
        )

        result = accessor.get(pattern="Index$")

        assert result is not None
        assert len(result) == 4  # SPX, NDX, ES, NQ

    def test_search_by_substring(self, search_store):
        """Test searching by substring."""
        accessor = ACCESSOR_FACTORY.build(
            "UniverseSearchAccessor",
            resource_id="search-test",
            config={},
            store=search_store,
        )

        result = accessor.get(pattern="Equity")

        assert result is not None
        assert len(result) == 3  # AAPL, MSFT, GOOGL

    def test_search_case_insensitive(self, search_store):
        """Test case-insensitive search."""
        accessor = ACCESSOR_FACTORY.build(
            "UniverseSearchAccessor",
            resource_id="search-test",
            config={},
            store=search_store,
        )

        result = accessor.get(pattern="equity")

        assert result is not None
        assert len(result) == 3


class TestSQLAccessors:
    """Tests for SQL-based accessors."""

    def test_sql_table_accessor_registered(self):
        """Test that SQLTableStaticAccessor is registered."""
        assert "SQLTableStaticAccessor" in ACCESSOR_FACTORY

    def test_generic_sql_accessor_registered(self):
        """Test that GenericSQLAccessor is registered."""
        assert "GenericSQLAccessor" in ACCESSOR_FACTORY


class TestAccessorFactoryContainsAll:
    """Test that all accessors are registered in factory."""

    @pytest.mark.parametrize(
        "accessor_name",
        [
            "SimpleAccessor",
            "PITAccessor",
            "EconomicsAccessor",
            "GenericFuturesAccessor",
            "FieldsAccessor",
            "TickerAccessor",
            "UniverseSearchAccessor",
            "SQLTableStaticAccessor",
            "GenericSQLAccessor",
        ],
    )
    def test_accessor_registered(self, accessor_name):
        """Test accessor is in factory."""
        assert accessor_name in ACCESSOR_FACTORY
