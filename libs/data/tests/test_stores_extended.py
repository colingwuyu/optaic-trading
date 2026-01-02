"""Tests for Extended Store Implementations (flatfile.py, config.py)."""

from __future__ import annotations


import pandas as pd
import pytest

from libs.data.registry import STORE_FACTORY


class TestFlatFileStore:
    """Tests for FlatFileStore."""

    @pytest.fixture
    def temp_csv_file(self, tmp_path):
        """Create a temporary CSV file."""
        csv_path = tmp_path / "test_data.csv"
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=10),
                "close": [100 + i for i in range(10)],
                "volume": [1000 * (i + 1) for i in range(10)],
            }
        )
        df.to_csv(csv_path, index=False)
        return csv_path

    @pytest.fixture
    def temp_excel_file(self, tmp_path):
        """Create a temporary Excel file."""
        pytest.importorskip("openpyxl")
        excel_path = tmp_path / "test_data.xlsx"
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=10),
                "price": [50 + i * 0.5 for i in range(10)],
            }
        )
        df.to_excel(excel_path, index=False)
        return excel_path

    @pytest.fixture
    def temp_parquet_file(self, tmp_path):
        """Create a temporary Parquet file."""
        parquet_path = tmp_path / "test_data.parquet"
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=10),
                "value": [i * 10 for i in range(10)],
            }
        )
        df.to_parquet(parquet_path, index=False)
        return parquet_path

    def test_flatfilestore_registered(self):
        """Test that FlatFileStore is registered."""
        assert "FlatFileStore" in STORE_FACTORY

    def test_read_csv_basic(self, temp_csv_file, tmp_path):
        """Test reading a basic CSV file."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-csv",
            config={"file_path": str(temp_csv_file)},
            data_dir=tmp_path,
        )

        df = store.read()

        assert df is not None
        assert len(df) == 10
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_read_csv_with_date_column(self, temp_csv_file, tmp_path):
        """Test reading CSV with date parsing."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-csv-date",
            config={
                "file_path": str(temp_csv_file),
                "date_column": "date",
            },
            data_dir=tmp_path,
        )

        df = store.read()

        assert df is not None
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_read_csv_with_date_filter(self, temp_csv_file, tmp_path):
        """Test reading CSV with date filtering."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-csv-filter",
            config={
                "file_path": str(temp_csv_file),
                "date_column": "date",
            },
            data_dir=tmp_path,
        )

        df = store.read(
            start_date="2024-01-03",
            end_date="2024-01-07",
        )

        assert df is not None
        assert len(df) == 5

    def test_read_csv_with_columns(self, temp_csv_file, tmp_path):
        """Test reading CSV with column selection."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-csv-cols",
            config={
                "file_path": str(temp_csv_file),
            },
            data_dir=tmp_path,
        )

        df = store.read(columns=["date", "close"])

        assert df is not None
        assert "close" in df.columns
        assert "volume" not in df.columns

    def test_read_excel(self, temp_excel_file, tmp_path):
        """Test reading an Excel file."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-excel",
            config={"file_path": str(temp_excel_file)},
            data_dir=tmp_path,
        )

        df = store.read()

        assert df is not None
        assert len(df) == 10
        assert "price" in df.columns

    def test_read_parquet(self, temp_parquet_file, tmp_path):
        """Test reading a Parquet file."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-parquet",
            config={"file_path": str(temp_parquet_file)},
            data_dir=tmp_path,
        )

        df = store.read()

        assert df is not None
        assert len(df) == 10
        assert "value" in df.columns

    def test_get_columns(self, temp_csv_file, tmp_path):
        """Test getting column names."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-csv-cols",
            config={"file_path": str(temp_csv_file)},
            data_dir=tmp_path,
        )

        columns = store.get_columns()

        assert "date" in columns
        assert "close" in columns
        assert "volume" in columns

    def test_exists(self, temp_csv_file, tmp_path):
        """Test checking if file exists."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-exists",
            config={"file_path": str(temp_csv_file)},
            data_dir=tmp_path,
        )

        assert store.exists() is True

    def test_not_exists(self, tmp_path):
        """Test checking non-existent file."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-not-exists",
            config={"file_path": str(tmp_path / "nonexistent.csv")},
            data_dir=tmp_path,
        )

        assert store.exists() is False

    def test_write_csv(self, tmp_path):
        """Test writing CSV file."""
        store = STORE_FACTORY.build(
            "FlatFileStore",
            resource_id="test-write",
            config={"file_path": str(tmp_path / "output.csv")},
            data_dir=tmp_path,
        )

        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        rows = store.write(df)

        assert rows == 3
        assert (tmp_path / "output.csv").exists()


class TestConfigStore:
    """Tests for ConfigStore."""

    @pytest.fixture
    def temp_yaml_file(self, tmp_path):
        """Create a temporary YAML config file."""
        yaml_path = tmp_path / "config.yaml"
        yaml_content = """
settings:
  database:
    host: localhost
    port: 5432
  features:
    - feature1
    - feature2
    - feature3
parameters:
  alpha: 0.05
  beta: 0.95
"""
        yaml_path.write_text(yaml_content)
        return yaml_path

    def test_configstore_registered(self):
        """Test that ConfigStore is registered."""
        assert "ConfigStore" in STORE_FACTORY

    def test_read_yaml_config(self, temp_yaml_file, tmp_path):
        """Test reading YAML config file."""
        store = STORE_FACTORY.build(
            "ConfigStore",
            resource_id="test-config",
            config={"file_path": str(temp_yaml_file)},
            data_dir=tmp_path,
        )

        result = store.read()

        assert result is not None
        assert isinstance(result, dict)
        assert "settings" in result
        assert "parameters" in result

    def test_read_yaml_nested_values(self, temp_yaml_file, tmp_path):
        """Test reading nested YAML values."""
        store = STORE_FACTORY.build(
            "ConfigStore",
            resource_id="test-config-nested",
            config={"file_path": str(temp_yaml_file)},
            data_dir=tmp_path,
        )

        result = store.read()

        assert result["settings"]["database"]["host"] == "localhost"
        assert result["settings"]["database"]["port"] == 5432
        assert len(result["settings"]["features"]) == 3

    def test_read_yaml_parameters(self, temp_yaml_file, tmp_path):
        """Test reading numeric parameters."""
        store = STORE_FACTORY.build(
            "ConfigStore",
            resource_id="test-config-params",
            config={"file_path": str(temp_yaml_file)},
            data_dir=tmp_path,
        )

        result = store.read()

        assert result["parameters"]["alpha"] == 0.05
        assert result["parameters"]["beta"] == 0.95

    def test_exists(self, temp_yaml_file, tmp_path):
        """Test checking if config file exists."""
        store = STORE_FACTORY.build(
            "ConfigStore",
            resource_id="test-config-exists",
            config={"file_path": str(temp_yaml_file)},
            data_dir=tmp_path,
        )

        assert store.exists() is True

    def test_not_exists(self, tmp_path):
        """Test checking non-existent config file."""
        store = STORE_FACTORY.build(
            "ConfigStore",
            resource_id="test-config-not-exists",
            config={"file_path": str(tmp_path / "nonexistent.yaml")},
            data_dir=tmp_path,
        )

        assert store.exists() is False

    def test_write_not_supported(self, temp_yaml_file, tmp_path):
        """Test that write raises error (read-only store)."""
        store = STORE_FACTORY.build(
            "ConfigStore",
            resource_id="test-config-readonly",
            config={"file_path": str(temp_yaml_file)},
            data_dir=tmp_path,
        )

        with pytest.raises(NotImplementedError):
            store.write({"key": "value"})


class TestStoreFactoryContainsNewStores:
    """Test that new stores are registered in factory."""

    @pytest.mark.parametrize(
        "store_name",
        ["FlatFileStore", "ConfigStore"],
    )
    def test_store_registered(self, store_name):
        """Test store is in factory."""
        assert store_name in STORE_FACTORY
