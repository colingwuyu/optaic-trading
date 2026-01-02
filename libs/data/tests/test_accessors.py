"""Tests for accessor implementations."""

from datetime import date

import pytest

from libs.data.access.pit import PITAccessor, PITRequest
from libs.data.access.simple import SimpleAccessor


class TestSimpleAccessor:
    """Tests for SimpleAccessor."""

    def test_get_basic(self, temp_data_dir, sample_timeseries_df):
        """Test basic get without filtering."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        accessor = SimpleAccessor(
            resource_id="test",
            store=store,
            config={"primary_key": "date"},
        )

        df = accessor.get()
        assert len(df) == len(sample_timeseries_df)

    def test_get_with_date_range(self, temp_data_dir, sample_timeseries_df):
        """Test get with date filtering."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        accessor = SimpleAccessor(
            resource_id="test",
            store=store,
            config={"primary_key": "date"},
        )

        df = accessor.get(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
        )
        assert len(df) == 10

    def test_get_with_columns(self, temp_data_dir, sample_timeseries_df):
        """Test get with column selection."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        accessor = SimpleAccessor(
            resource_id="test",
            store=store,
            config={},
        )

        df = accessor.get(columns=["close"])
        assert "close" in df.columns
        assert "volume" not in df.columns

    def test_get_with_as_of_date(self, temp_data_dir, sample_timeseries_df):
        """Test get with as_of_date cutoff."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        accessor = SimpleAccessor(
            resource_id="test",
            store=store,
            config={"primary_key": "date"},
        )

        # Get data as of Jan 20
        df = accessor.get(as_of_date=date(2024, 1, 20))
        # Should only include rows up to Jan 20
        assert len(df) <= 20

    def test_get_output_columns(self, temp_data_dir, sample_timeseries_df):
        """Test get_output_columns delegates to store."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        accessor = SimpleAccessor(
            resource_id="test",
            store=store,
            config={},
        )

        columns = accessor.get_output_columns()
        assert "date" in columns
        assert "close" in columns


class TestPITAccessor:
    """Tests for PITAccessor (point-in-time)."""

    def test_requires_as_of_date(self, temp_data_dir, sample_pit_df):
        """Test that as_of_date is required."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_pit_df)

        accessor = PITAccessor(
            resource_id="test",
            store=store,
            config={
                "observation_date_col": "date",
                "knowledge_date_col": "knowledge_date",
            },
        )

        with pytest.raises(ValueError, match="as_of_date"):
            accessor.get()

    def test_pit_filtering(self, temp_data_dir, sample_pit_df):
        """Test PIT accessor returns correct version based on as_of_date."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={"primary_key": "date"},
            data_dir=temp_data_dir,
        )
        store.write(sample_pit_df)

        accessor = PITAccessor(
            resource_id="test",
            store=store,
            config={
                "observation_date_col": "date",
                "knowledge_date_col": "knowledge_date",
            },
        )

        # Query as of a date between initial and revised estimates
        # Should get initial estimates only
        df = accessor.get(as_of_date=date(2024, 2, 15))

        # Each observation should appear only once (latest known version)
        assert df["date"].is_unique

    def test_pit_request_model(self):
        """Test PITRequest requires as_of_date."""
        # Valid request
        req = PITRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            as_of_date=date(2024, 6, 1),
        )
        assert req.as_of_date == date(2024, 6, 1)

        # Invalid - missing as_of_date
        with pytest.raises(ValueError):
            PITRequest(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
            )

    def test_get_output_columns_excludes_knowledge_date(
        self, temp_data_dir, sample_pit_df
    ):
        """Test output columns exclude knowledge_date by default."""
        from libs.data.store.virtual import VirtualStore

        store = VirtualStore(
            resource_id="test",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_pit_df)

        accessor = PITAccessor(
            resource_id="test",
            store=store,
            config={
                "observation_date_col": "date",
                "knowledge_date_col": "knowledge_date",
            },
        )

        columns = accessor.get_output_columns()
        assert "knowledge_date" not in columns
        assert "value" in columns

    def test_missing_knowledge_date_column(self, temp_data_dir, sample_timeseries_df):
        """Test error when knowledge_date column is missing."""
        from libs.data.store.virtual import VirtualStore

        # Use timeseries data (no knowledge_date)
        store = VirtualStore(
            resource_id="test",
            config={},
            data_dir=temp_data_dir,
        )
        store.write(sample_timeseries_df)

        accessor = PITAccessor(
            resource_id="test",
            store=store,
            config={
                "observation_date_col": "date",
                "knowledge_date_col": "knowledge_date",
            },
        )

        with pytest.raises(ValueError, match="knowledge_date"):
            accessor.get(as_of_date=date(2024, 1, 15))
