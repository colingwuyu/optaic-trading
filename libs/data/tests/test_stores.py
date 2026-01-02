"""Tests for store implementations."""

from datetime import date

import pandas as pd
import pytest

from libs.data.store.parquet import ParquetStore
from libs.data.store.sqlite import SQLiteStore
from libs.data.store.virtual import VirtualStore


class TestVirtualStore:
    """Tests for VirtualStore."""

    def test_write_and_read(self, temp_data_dir, sample_timeseries_df):
        """Test basic write and read."""
        store = VirtualStore(
            resource_id="test_virtual",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )

        # Initially no data
        assert not store.exists()

        # Write data
        rows_written = store.write(sample_timeseries_df)
        assert rows_written == len(sample_timeseries_df)
        assert store.exists()

        # Read data back
        df = store.read()
        assert len(df) == len(sample_timeseries_df)
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_date_filtering(self, temp_data_dir, sample_timeseries_df):
        """Test date range filtering."""
        store = VirtualStore(
            resource_id="test_filter",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        # Filter to first 10 days
        df = store.read(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
        )
        assert len(df) == 10

    def test_column_selection(self, temp_data_dir, sample_timeseries_df):
        """Test column filtering."""
        store = VirtualStore(
            resource_id="test_cols",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        df = store.read(columns=["close"])
        assert "close" in df.columns
        assert "volume" not in df.columns

    def test_get_columns(self, temp_data_dir, sample_timeseries_df):
        """Test get_columns returns column names."""
        store = VirtualStore(
            resource_id="test_get_cols",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        columns = store.get_columns()
        assert "date" in columns
        assert "close" in columns
        assert "volume" in columns

    def test_get_row_count(self, temp_data_dir, sample_timeseries_df):
        """Test get_row_count."""
        store = VirtualStore(
            resource_id="test_count",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        assert store.get_row_count() == len(sample_timeseries_df)

    def test_clear(self, temp_data_dir, sample_timeseries_df):
        """Test clear removes data."""
        store = VirtualStore(
            resource_id="test_clear",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)
        assert store.exists()

        store.clear()
        assert not store.exists()

    def test_append_mode(self, temp_data_dir):
        """Test append mode adds to existing data."""
        store = VirtualStore(
            resource_id="test_append",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )

        # Write first batch
        df1 = pd.DataFrame({"date": ["2024-01-01"], "value": [1]})
        store.write(df1)
        assert store.get_row_count() == 1

        # Append second batch
        df2 = pd.DataFrame({"date": ["2024-01-02"], "value": [2]})
        store.write(df2, mode="append")
        assert store.get_row_count() == 2


class TestParquetStore:
    """Tests for ParquetStore."""

    def test_write_and_read(self, temp_data_dir, sample_timeseries_df):
        """Test basic write and read."""
        store = ParquetStore(
            resource_id="test_parquet",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )

        # Write data
        rows_written = store.write(sample_timeseries_df)
        assert rows_written == len(sample_timeseries_df)
        assert store.exists()

        # Read data back
        df = store.read()
        assert len(df) == len(sample_timeseries_df)

    def test_date_filtering(self, temp_data_dir, sample_timeseries_df):
        """Test date range filtering."""
        store = ParquetStore(
            resource_id="test_parquet_filter",
            config={"primary_key": "date", "partition_by_year": False},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        df = store.read(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
        )
        assert len(df) == 10

    def test_get_storage_path(self, temp_data_dir):
        """Test get_storage_path returns the parquet directory."""
        store = ParquetStore(
            resource_id="test_path",
            config={},
            data_dir=temp_data_dir,
        )
        path = store.get_storage_path()
        assert path is not None
        assert "parquet" in str(path)
        assert "test_path" in str(path)

    def test_overwrite_mode(self, temp_data_dir, sample_timeseries_df):
        """Test overwrite mode replaces data."""
        store = ParquetStore(
            resource_id="test_overwrite",
            config={"primary_key": "date", "partition_by_year": False},
            data_dir=temp_data_dir,
        )

        # Write initial data
        store.write(sample_timeseries_df)
        initial_count = store.get_row_count()

        # Overwrite with smaller dataset
        small_df = sample_timeseries_df.head(10)
        store.write(small_df, mode="overwrite")

        assert store.get_row_count() == 10
        assert store.get_row_count() < initial_count

    def test_delete(self, temp_data_dir, sample_timeseries_df):
        """Test delete removes the store."""
        store = ParquetStore(
            resource_id="test_delete",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)
        assert store.exists()

        store.delete()
        assert not store.exists()


class TestSQLiteStore:
    """Tests for SQLiteStore."""

    def test_requires_table_name(self, temp_data_dir):
        """Test SQLiteStore requires table_name in config."""
        with pytest.raises(ValueError, match="table_name"):
            SQLiteStore(
                resource_id="test_sqlite",
                config={},  # Missing table_name
                data_dir=temp_data_dir,
            )

    def test_write_requires_writable_flag(self, temp_data_dir, sample_timeseries_df):
        """Test write fails without writable flag."""
        store = SQLiteStore(
            resource_id="test_readonly",
            config={"table_name": "test_table"},
            data_dir=temp_data_dir,
        )

        with pytest.raises(NotImplementedError, match="read-only"):
            store.write(sample_timeseries_df)

    def test_writable_write_and_read(self, temp_data_dir, sample_timeseries_df):
        """Test write and read with writable flag."""
        store = SQLiteStore(
            resource_id="test_writable",
            config={
                "table_name": "test_table",
                "writable": True,
                "primary_key": "date",
            },
            data_dir=temp_data_dir,
        )

        # Write data
        rows_written = store.write(sample_timeseries_df)
        assert rows_written == len(sample_timeseries_df)
        assert store.exists()

        # Read data back
        df = store.read()
        assert len(df) == len(sample_timeseries_df)

    def test_get_columns(self, temp_data_dir, sample_timeseries_df):
        """Test get_columns from SQLite table."""
        store = SQLiteStore(
            resource_id="test_cols",
            config={
                "table_name": "test_table",
                "writable": True,
            },
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        columns = store.get_columns()
        assert "date" in columns
        assert "close" in columns
        assert "volume" in columns

    def test_execute_query(self, temp_data_dir, sample_timeseries_df):
        """Test execute_query for custom SQL."""
        store = SQLiteStore(
            resource_id="test_query",
            config={
                "table_name": "test_table",
                "writable": True,
            },
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        df = store.execute_query("SELECT COUNT(*) as cnt FROM test_table")
        assert df.iloc[0]["cnt"] == len(sample_timeseries_df)
