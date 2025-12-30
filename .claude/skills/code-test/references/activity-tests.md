# Activity Emission Test Patterns

## Test All Mutation Methods

For each service method that mutates state, generate a test like:

```python
import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

class TestServiceActivities:

    @pytest.mark.asyncio
    async def test_create_emits_activity(self, db_session, actor_id, tenant_id):
        """Verify create emits signal.created activity."""
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("libs.core.activity.record_activity_with_outbox") as mock:
            mock.return_value = AsyncMock()

            result = await service.create(
                SignalCreateDTO(name="test", signal_type="alpha"),
                parent_id=uuid4()
            )

            # Verify activity was emitted
            mock.assert_called_once()
            envelope = mock.call_args.kwargs["envelope"]

            # Required fields
            assert envelope.action == "signal.created"
            assert envelope.actor_principal_id == actor_id
            assert envelope.tenant_id == tenant_id
            assert envelope.resource_type == "signal"
            assert envelope.resource_id is not None

    @pytest.mark.asyncio
    async def test_update_emits_activity_with_changes(self, db_session, existing_signal):
        """Verify update emits activity with change details."""
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("libs.core.activity.record_activity_with_outbox") as mock:
            await service.update(
                existing_signal.id,
                SignalUpdateDTO(lookback_days=30)
            )

            envelope = mock.call_args.kwargs["envelope"]
            assert envelope.action == "signal.updated"
            assert "changes" in envelope.payload
            assert "lookback_days" in envelope.payload["changes"]

    @pytest.mark.asyncio
    async def test_delete_emits_activity(self, db_session, existing_signal):
        """Verify delete emits signal.deleted activity."""
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("libs.core.activity.record_activity_with_outbox") as mock:
            await service.delete(existing_signal.id)

            envelope = mock.call_args.kwargs["envelope"]
            assert envelope.action == "signal.deleted"
```

## Integration Test (Outbox Pattern)

```python
@pytest.mark.asyncio
async def test_activity_reaches_outbox(self, db_session):
    """Verify activity is persisted to outbox for reliable delivery."""
    service = SignalService(db_session, actor_id, tenant_id)

    signal = await service.create(dto, parent_id)
    await db_session.commit()

    # Check outbox has entry
    result = await db_session.execute(
        select(OutboxEntry).where(
            OutboxEntry.payload["resource_id"].astext == str(signal.resource_id)
        )
    )
    entry = result.scalar_one()

    assert entry is not None
    assert entry.payload["action"] == "signal.created"
```

## Correlation ID Test

```python
@pytest.mark.asyncio
async def test_workflow_uses_same_correlation_id(self):
    """Verify related activities share correlation_id."""
    correlation_id = uuid4()
    activities = []

    with patch("libs.core.activity.record_activity_with_outbox") as mock:
        mock.side_effect = lambda **kw: activities.append(kw["envelope"])

        await promotion_workflow(correlation_id)

    # All activities should share correlation_id
    for activity in activities:
        assert activity.correlation_id == correlation_id
```
