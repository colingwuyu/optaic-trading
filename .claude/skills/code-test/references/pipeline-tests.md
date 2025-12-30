# Pipeline and Data Test Patterns

## PIT Correctness Tests

### Test No Lookahead Bias

```python
import pytest
from datetime import date, datetime

class TestPITCorrectness:

    def test_query_excludes_future_knowledge(self, accessor, db_session):
        """Data with future knowledge_date should not be returned."""
        # Insert data known in the future
        insert_price(
            db_session,
            date=date(2024, 1, 1),
            value=100.0,
            knowledge_date=datetime(2024, 1, 15)  # Known Jan 15
        )

        # Query as of Jan 10 - should NOT see this data
        result = accessor.query(
            as_of_date=date(2024, 1, 1),
            knowledge_cutoff=datetime(2024, 1, 10)
        )

        assert len(result) == 0

    def test_query_includes_older_knowledge(self, accessor, db_session):
        """Data with older knowledge_date should be returned."""
        insert_price(
            db_session,
            date=date(2024, 1, 1),
            value=100.0,
            knowledge_date=datetime(2024, 1, 5)  # Known Jan 5
        )

        # Query as of Jan 10 - should see this data
        result = accessor.query(
            as_of_date=date(2024, 1, 1),
            knowledge_cutoff=datetime(2024, 1, 10)
        )

        assert len(result) == 1
        assert result[0]["value"] == 100.0

    def test_latest_vintage_selected(self, accessor, db_session):
        """When multiple vintages exist, latest valid one is selected."""
        # Insert two vintages
        insert_price(db_session, date=date(2024, 1, 1), value=100.0,
                     knowledge_date=datetime(2024, 1, 5))
        insert_price(db_session, date=date(2024, 1, 1), value=101.0,
                     knowledge_date=datetime(2024, 1, 8))  # Revision

        result = accessor.query(
            as_of_date=date(2024, 1, 1),
            knowledge_cutoff=datetime(2024, 1, 10)
        )

        assert result[0]["value"] == 101.0  # Latest revision
```

## Arrow Schema Tests

```python
import pyarrow as pa

def test_schema_has_knowledge_date(self, dataset):
    """Verify schema includes knowledge_date field."""
    schema = dataset.get_schema()

    field_names = [f.name for f in schema]
    assert "knowledge_date" in field_names

    kd_field = schema.field("knowledge_date")
    assert pa.types.is_timestamp(kd_field.type)

def test_schema_validation(self, pipeline, sample_data):
    """Verify pipeline validates data against schema."""
    # Create invalid data (missing required field)
    invalid_data = sample_data.drop("knowledge_date")

    with pytest.raises(SchemaValidationError):
        pipeline.ingest(invalid_data)
```

## Data Quality Check Tests

```python
def test_no_future_dates_check(self, checker, df):
    """Verify no_future_dates quality check works."""
    # Insert row with future date
    df_with_future = pd.concat([df, pd.DataFrame([{
        "date": date.today() + timedelta(days=30),
        "value": 100.0
    }])])

    result = checker.run_check("no_future_dates", df_with_future)

    assert not result.passed
    assert "future" in result.message.lower()

def test_no_duplicates_check(self, checker, df):
    """Verify no_duplicates quality check works."""
    df_with_dups = pd.concat([df, df.iloc[[0]]])

    result = checker.run_check("no_duplicates", df_with_dups,
                               key_cols=["date", "symbol"])

    assert not result.passed
```

## Activity Emission for Data Refresh

```python
@pytest.mark.asyncio
async def test_refresh_emits_activity(self, pipeline, db_session):
    """Verify dataset refresh emits activity."""
    with patch("libs.core.activity.record_activity_with_outbox") as mock:
        await pipeline.refresh(dataset_id, date="2024-01-15")

        envelope = mock.call_args.kwargs["envelope"]
        assert envelope.action == "dataset.refreshed"
        assert "date" in envelope.payload
```
