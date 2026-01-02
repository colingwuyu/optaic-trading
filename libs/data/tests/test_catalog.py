"""Tests for catalog types."""

from datetime import date

import pytest

from libs.data.catalog import (
    BackendType,
    DataPreviewRequest,
    DataPreviewResponse,
    DatasetKind,
    DatasetStatus,
    UpdateFrequency,
)


class TestBackendType:
    """Tests for BackendType enum."""

    def test_backend_types_exist(self):
        """Verify all expected backend types exist."""
        assert BackendType.SQLITE == "sqlite"
        assert BackendType.PARQUET == "parquet"
        assert BackendType.VIRTUAL == "virtual"
        assert BackendType.CONFIG == "config"
        assert BackendType.FLATFILE == "flatfile"
        assert BackendType.CACHE == "cache"


class TestDatasetKind:
    """Tests for DatasetKind enum."""

    def test_dataset_kinds_exist(self):
        """Verify all expected dataset kinds exist."""
        assert DatasetKind.TIME_SERIES == "time_series"
        assert DatasetKind.VINTAGE == "vintage"
        assert DatasetKind.STATIC == "static"


class TestDatasetStatus:
    """Tests for DatasetStatus enum."""

    def test_status_values(self):
        """Verify all expected status values exist."""
        assert DatasetStatus.NOT_INITIALIZED == "not_initialized"
        assert DatasetStatus.READY == "ready"
        assert DatasetStatus.STALE == "stale"
        assert DatasetStatus.STALE_SOURCE_DELAYED == "stale_source_delayed"
        assert DatasetStatus.ERROR == "error"


class TestUpdateFrequency:
    """Tests for UpdateFrequency model."""

    def test_daily_frequency_expected_date(self):
        """Test daily frequency returns T-1."""
        freq = UpdateFrequency(frequency="daily")
        today = date(2024, 6, 15)  # Saturday
        expected = freq.get_expected_date(today)
        assert expected == date(2024, 6, 14)  # Friday

    def test_daily_business_days_monday(self):
        """Test business days only: Monday expects Friday."""
        freq = UpdateFrequency(frequency="daily", business_days_only=True)
        monday = date(2024, 6, 17)
        expected = freq.get_expected_date(monday)
        assert expected == date(2024, 6, 14)  # Friday (3 days back)

    def test_daily_business_days_tuesday(self):
        """Test business days only: Tuesday expects Monday."""
        freq = UpdateFrequency(frequency="daily", business_days_only=True)
        tuesday = date(2024, 6, 18)
        expected = freq.get_expected_date(tuesday)
        assert expected == date(2024, 6, 17)  # Monday (1 day back)

    def test_weekly_frequency(self):
        """Test weekly frequency defaults to last Friday."""
        freq = UpdateFrequency(frequency="weekly")
        wednesday = date(2024, 6, 19)
        expected = freq.get_expected_date(wednesday)
        # Should return last Friday
        assert expected.weekday() == 4  # Friday

    def test_monthly_frequency(self):
        """Test monthly frequency returns last day of previous month."""
        freq = UpdateFrequency(frequency="monthly")
        mid_june = date(2024, 6, 15)
        expected = freq.get_expected_date(mid_june)
        assert expected == date(2024, 5, 31)  # May 31

    def test_quarterly_frequency(self):
        """Test quarterly frequency returns last day of previous quarter."""
        freq = UpdateFrequency(frequency="quarterly")
        q2 = date(2024, 5, 15)  # Q2
        expected = freq.get_expected_date(q2)
        assert expected == date(2024, 3, 31)  # End of Q1

    def test_annually_frequency(self):
        """Test annually frequency returns Dec 31 of previous year."""
        freq = UpdateFrequency(frequency="annually")
        current_year = date(2024, 6, 15)
        expected = freq.get_expected_date(current_year)
        assert expected == date(2023, 12, 31)

    def test_irregular_frequency_returns_none(self):
        """Test irregular frequency returns None."""
        freq = UpdateFrequency(frequency="irregular")
        expected = freq.get_expected_date(date(2024, 6, 15))
        assert expected is None

    def test_custom_frequency(self):
        """Test custom frequency with custom_days."""
        freq = UpdateFrequency(frequency="custom", custom_days=7)
        today = date(2024, 6, 15)
        expected = freq.get_expected_date(today)
        assert expected == date(2024, 6, 8)


class TestDataPreviewRequest:
    """Tests for DataPreviewRequest model."""

    def test_default_values(self):
        """Test default request values."""
        req = DataPreviewRequest()
        assert req.start_date == date(1900, 1, 1)
        assert req.end_date == date(2099, 12, 31)
        assert req.as_of_date is None
        assert req.limit == 1000
        assert req.columns is None

    def test_custom_values(self):
        """Test custom request values."""
        req = DataPreviewRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            as_of_date=date(2024, 6, 1),
            limit=500,
            columns=["close", "volume"],
        )
        assert req.start_date == date(2024, 1, 1)
        assert req.end_date == date(2024, 12, 31)
        assert req.as_of_date == date(2024, 6, 1)
        assert req.limit == 500
        assert req.columns == ["close", "volume"]

    def test_limit_validation(self):
        """Test limit must be >= 1 and <= 100000."""
        with pytest.raises(ValueError):
            DataPreviewRequest(limit=0)
        with pytest.raises(ValueError):
            DataPreviewRequest(limit=100001)


class TestDataPreviewResponse:
    """Tests for DataPreviewResponse model."""

    def test_response_creation(self):
        """Test creating a preview response."""
        resp = DataPreviewResponse(
            resource_id="abc123",
            resource_name="test_dataset",
            row_count=100,
            column_names=["date", "close", "volume"],
            data=[{"date": "2024-01-01", "close": 100, "volume": 1000}],
            truncated=False,
            as_of_date=date(2024, 6, 1),
        )
        assert resp.resource_id == "abc123"
        assert resp.resource_name == "test_dataset"
        assert resp.row_count == 100
        assert len(resp.column_names) == 3
        assert len(resp.data) == 1
        assert resp.truncated is False
        assert resp.as_of_date == date(2024, 6, 1)
