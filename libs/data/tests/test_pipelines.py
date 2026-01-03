"""Tests for Pipeline Implementations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from libs.data.pipelines.base import DataPipeline
from libs.data.registry import PIPELINE_FACTORY
from libs.data.store.virtual import VirtualStore


class TestDataPipelineBase:
    """Tests for DataPipeline base class."""

    def test_base_pipeline_is_abstract(self):
        """Test that DataPipeline cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DataPipeline("test", {})

    def test_concrete_pipeline_requires_extract_transform(self):
        """Test that concrete implementations need extract and transform."""

        class IncompletePipeline(DataPipeline):
            pass

        with pytest.raises(TypeError):
            IncompletePipeline("test", {})


class TestExpressionPipeline:
    """Tests for ExpressionPipeline."""

    def test_expression_pipeline_registered(self):
        """Test that ExpressionPipeline is registered."""
        assert "ExpressionPipeline" in PIPELINE_FACTORY

    def test_requires_expression_config(self):
        """Test that expression is required in config."""
        with pytest.raises(ValueError, match="requires 'expression'"):
            PIPELINE_FACTORY.build(
                "ExpressionPipeline",
                resource_id="test-expr",
                config={},  # Missing expression
            )

    def test_simple_expression(self, tmp_path):
        """Test evaluating a simple expression."""
        store = VirtualStore("expr-output", {}, data_dir=tmp_path)

        pipeline = PIPELINE_FACTORY.build(
            "ExpressionPipeline",
            resource_id="test-expr",
            config={"expression": "$close * 2"},
            store=store,
        )

        # Create context with close prices
        context = {
            "close": pd.Series(
                [100, 101, 102],
                index=pd.date_range("2024-01-01", periods=3),
            )
        }

        result = pipeline.run(preview=True, **context)

        assert result is not None
        assert len(result) == 3
        assert result.iloc[0, 0] == 200  # 100 * 2

    def test_named_expression(self, tmp_path):
        """Test evaluating a named expression."""
        store = VirtualStore("expr-output", {}, data_dir=tmp_path)

        pipeline = PIPELINE_FACTORY.build(
            "ExpressionPipeline",
            resource_id="test-named-expr",
            config={"expression": "doubled: $close * 2"},
            store=store,
        )

        context = {
            "close": pd.Series(
                [100, 101, 102],
                index=pd.date_range("2024-01-01", periods=3),
            )
        }

        result = pipeline.run(preview=True, **context)

        assert result is not None
        assert "doubled" in result.columns or result.columns[0] == "doubled"

    def test_multiline_expression(self, tmp_path):
        """Test evaluating multiline expressions."""
        store = VirtualStore("expr-output", {}, data_dir=tmp_path)

        expression = """
        ma: MEAN($close, 3)
        signal: $close - $ma
        """

        pipeline = PIPELINE_FACTORY.build(
            "ExpressionPipeline",
            resource_id="test-multiline",
            config={"expression": expression},
            store=store,
        )

        context = {
            "close": pd.Series(
                [100, 101, 102, 103, 104],
                index=pd.date_range("2024-01-01", periods=5),
            )
        }

        result = pipeline.run(preview=True, return_all_intermediates=True, **context)

        assert result is not None

    def test_dict_expression(self, tmp_path):
        """Test evaluating dict-based expressions."""
        store = VirtualStore("expr-output", {}, data_dir=tmp_path)

        pipeline = PIPELINE_FACTORY.build(
            "ExpressionPipeline",
            resource_id="test-dict-expr",
            config={
                "expression": {
                    "returns": "DELTA($close, 1) / REF($close, 1)",
                }
            },
            store=store,
        )

        context = {
            "close": pd.Series(
                [100, 101, 102, 103, 104],
                index=pd.date_range("2024-01-01", periods=5),
            )
        }

        result = pipeline.run(preview=True, **context)

        assert result is not None

    def test_expression_with_context_loader(self, tmp_path):
        """Test expression pipeline with context loader."""
        store = VirtualStore("expr-output", {}, data_dir=tmp_path)

        def mock_loader(name, **kwargs):
            if name == "prices":
                return pd.DataFrame(
                    {"close": [100, 101, 102]},
                    index=pd.date_range("2024-01-01", periods=3),
                )
            return pd.DataFrame()

        pipeline = PIPELINE_FACTORY.build(
            "ExpressionPipeline",
            resource_id="test-ctx-loader",
            config={
                "expression": "$prices.close * 2",
                "constituents": ["prices"],
            },
            store=store,
            context_loader=mock_loader,
        )

        result = pipeline.run(preview=True)

        assert result is not None


class TestFredPipeline:
    """Tests for FredPipeline."""

    def test_fred_pipeline_registered(self):
        """Test that FredPipeline is registered."""
        assert "FredPipeline" in PIPELINE_FACTORY

    def test_requires_series_id(self):
        """Test that series_id is required."""
        with pytest.raises(ValueError, match="requires 'series_id'"):
            PIPELINE_FACTORY.build(
                "FredPipeline",
                resource_id="test-fred",
                config={},  # Missing series_id
            )

    def test_creates_without_api_key(self):
        """Test pipeline can be created without API key (will fail on extract)."""
        with patch.dict("os.environ", {}, clear=True):
            pipeline = PIPELINE_FACTORY.build(
                "FredPipeline",
                resource_id="test-fred",
                config={"series_id": "GDP"},
            )

            assert pipeline is not None
            assert pipeline.series_id == "GDP"

    @patch("libs.data.pipelines.fred.Fred")
    def test_extract_calls_fred_api(self, mock_fred_class):
        """Test that extract calls FRED API."""
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = pd.Series(
            [100, 101, 102],
            index=pd.date_range("2024-01-01", periods=3),
            name="value",
        )
        mock_fred_class.return_value = mock_fred

        with patch.dict("os.environ", {"FRED_API_KEY": "test-key"}):
            # Reimport to pick up mocked Fred
            from libs.data.pipelines import fred

            pipeline = fred.FredPipeline(
                resource_id="test-fred",
                config={"series_id": "GDP", "vintage": False},
            )
            pipeline.fred = mock_fred

            result = pipeline.extract()

            assert result is not None
            mock_fred.get_series.assert_called_once()

    def test_transform_regular_data(self):
        """Test transforming regular (non-vintage) data."""
        pipeline = PIPELINE_FACTORY.build(
            "FredPipeline",
            resource_id="test-fred",
            config={"series_id": "GDP", "vintage": False},
        )

        raw_data = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=5),
                "value": [100, 101, 102, 103, 104],
            }
        )

        result = pipeline.transform(raw_data)

        assert result is not None
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_transform_vintage_data(self):
        """Test transforming vintage data."""
        pipeline = PIPELINE_FACTORY.build(
            "FredPipeline",
            resource_id="test-fred-vintage",
            config={"series_id": "GDP", "vintage": True},
        )

        raw_data = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01"]),
                "realtime_start": pd.to_datetime(
                    ["2024-02-01", "2024-03-01", "2024-03-01"]
                ),
                "value": [100, 100.5, 101],
            }
        )

        result = pipeline.transform(raw_data)

        assert result is not None
        assert "release_date" in result.columns


class TestSQLiteUpdatePipeline:
    """Tests for SQLiteUpdatePipeline."""

    def test_sqlite_pipeline_registered(self):
        """Test that SQLiteUpdatePipeline is registered."""
        assert "SQLiteUpdatePipeline" in PIPELINE_FACTORY

    def test_requires_source_path(self):
        """Test that source_path is required."""
        with pytest.raises(ValueError, match="requires 'source_path'"):
            PIPELINE_FACTORY.build(
                "SQLiteUpdatePipeline",
                resource_id="test-sqlite",
                config={"target_path": "/tmp/local.db"},
            )

    def test_requires_target_path(self):
        """Test that target_path is required."""
        with pytest.raises(ValueError, match="requires 'target_path'"):
            PIPELINE_FACTORY.build(
                "SQLiteUpdatePipeline",
                resource_id="test-sqlite",
                config={"source_path": "/tmp/source.db"},
            )

    def test_extract_checks_source_exists(self, tmp_path):
        """Test that extract checks if source file exists."""
        source_path = tmp_path / "source.db"
        target_path = tmp_path / "target.db"

        pipeline = PIPELINE_FACTORY.build(
            "SQLiteUpdatePipeline",
            resource_id="test-sqlite",
            config={
                "source_path": str(source_path),
                "target_path": str(target_path),
            },
        )

        with pytest.raises(FileNotFoundError):
            pipeline.extract()

    def test_run_copies_file(self, tmp_path):
        """Test that run copies the file."""
        source_path = tmp_path / "source.db"
        target_path = tmp_path / "target.db"

        # Create source file
        source_path.write_text("test database content")

        pipeline = PIPELINE_FACTORY.build(
            "SQLiteUpdatePipeline",
            resource_id="test-sqlite",
            config={
                "source_path": str(source_path),
                "target_path": str(target_path),
            },
        )

        result = pipeline.run()

        assert result["status"] == "completed"
        assert target_path.exists()
        assert target_path.read_text() == "test database content"

    def test_run_creates_backup(self, tmp_path):
        """Test that run creates backup of existing file."""
        source_path = tmp_path / "source.db"
        target_path = tmp_path / "target.db"

        # Create both files
        source_path.write_text("new content")
        target_path.write_text("old content")

        pipeline = PIPELINE_FACTORY.build(
            "SQLiteUpdatePipeline",
            resource_id="test-sqlite",
            config={
                "source_path": str(source_path),
                "target_path": str(target_path),
            },
        )

        result = pipeline.run()

        assert result["status"] == "completed"
        # Check backup was created
        backups = list(tmp_path.glob("target.db.*.bak"))
        assert len(backups) == 1


class TestBloombergPipeline:
    """Tests for BloombergPipeline."""

    def test_bloomberg_pipeline_registered(self):
        """Test that BloombergPipeline is registered."""
        assert "BloombergPipeline" in PIPELINE_FACTORY
        assert "OHLCVBloombergPipeline" in PIPELINE_FACTORY

    def test_requires_ticker(self):
        """Test that ticker is required."""
        with pytest.raises(ValueError, match="requires 'ticker'"):
            PIPELINE_FACTORY.build(
                "BloombergPipeline",
                resource_id="test-bbg",
                config={"fields": {"PX_LAST": "close"}},
            )

    def test_requires_fields(self):
        """Test that fields is required."""
        with pytest.raises(ValueError, match="requires 'fields'"):
            PIPELINE_FACTORY.build(
                "BloombergPipeline",
                resource_id="test-bbg",
                config={"ticker": "SPX Index"},
            )

    def test_creates_with_dict_fields(self):
        """Test pipeline creation with dict-format fields."""
        pipeline = PIPELINE_FACTORY.build(
            "BloombergPipeline",
            resource_id="test-bbg",
            config={
                "ticker": "SPX Index",
                "fields": {"PX_LAST": "close", "PX_OPEN": "open"},
            },
        )

        assert pipeline is not None
        assert pipeline.ticker == "SPX Index"

    def test_creates_with_list_fields(self):
        """Test pipeline creation with list-format fields."""
        pipeline = PIPELINE_FACTORY.build(
            "BloombergPipeline",
            resource_id="test-bbg",
            config={
                "ticker": "SPX Index",
                "fields": ["PX_LAST", "PX_OPEN"],
                "rename_mapper": {"PX_LAST": "close"},
            },
        )

        assert pipeline is not None

    def test_resolve_fields_dict_format(self):
        """Test resolving dict-format fields config."""
        pipeline = PIPELINE_FACTORY.build(
            "BloombergPipeline",
            resource_id="test-bbg",
            config={
                "ticker": "SPX Index",
                "fields": {"PX_LAST": "close", "PX_OPEN": None},
            },
        )

        fields, rename_mapper = pipeline._resolve_fields_config()

        assert "PX_LAST" in fields
        assert "PX_OPEN" in fields
        assert rename_mapper == {"PX_LAST": "close"}

    def test_resolve_fields_list_format(self):
        """Test resolving list-format fields config."""
        pipeline = PIPELINE_FACTORY.build(
            "BloombergPipeline",
            resource_id="test-bbg",
            config={
                "ticker": "SPX Index",
                "fields": ["PX_LAST", "PX_OPEN"],
                "rename_mapper": {"PX_LAST": "close"},
            },
        )

        fields, rename_mapper = pipeline._resolve_fields_config()

        assert fields == ["PX_LAST", "PX_OPEN"]
        assert rename_mapper == {"PX_LAST": "close"}

    def test_transform_flattens_multiindex(self):
        """Test that transform flattens Bloomberg MultiIndex columns."""
        pipeline = PIPELINE_FACTORY.build(
            "BloombergPipeline",
            resource_id="test-bbg",
            config={
                "ticker": "SPX Index",
                "fields": {"PX_LAST": "close"},
            },
        )

        # Bloomberg returns MultiIndex with ticker as first level
        raw_data = pd.DataFrame(
            [[4500, 4510, 4520]],
            columns=pd.MultiIndex.from_tuples(
                [
                    ("SPX Index", "PX_LAST"),
                    ("SPX Index", "PX_OPEN"),
                    ("SPX Index", "PX_HIGH"),
                ]
            ),
            index=pd.date_range("2024-01-01", periods=1),
        )

        result = pipeline.transform(raw_data)

        assert result is not None
        # Should be flattened
        assert result.columns.nlevels == 1
        # Should be renamed
        assert "close" in result.columns

    def test_ohlcv_pipeline_has_preset_fields(self):
        """Test that OHLCVBloombergPipeline has preset fields."""
        pipeline = PIPELINE_FACTORY.build(
            "OHLCVBloombergPipeline",
            resource_id="test-ohlcv",
            config={"ticker": "SPX Index", "fields": {}},
        )

        fields, rename_mapper = pipeline._resolve_fields_config()

        assert "PX_OPEN" in fields
        assert "PX_HIGH" in fields
        assert "PX_LOW" in fields
        assert "PX_LAST" in fields
        assert "PX_VOLUME" in fields
        assert rename_mapper.get("PX_LAST") == "close"


class TestPipelineFactoryContainsAll:
    """Test that all pipelines are registered."""

    @pytest.mark.parametrize(
        "pipeline_name",
        [
            "ExpressionPipeline",
            "FredPipeline",
            "SQLiteUpdatePipeline",
            "BloombergPipeline",
            "OHLCVBloombergPipeline",
        ],
    )
    def test_pipeline_registered(self, pipeline_name):
        """Test pipeline is in factory."""
        assert pipeline_name in PIPELINE_FACTORY
