# Testing Activity Emission

## Mock-Based Testing

```python
import pytest
from unittest.mock import patch, AsyncMock

class TestSignalServiceActivities:

    @pytest.mark.asyncio
    async def test_create_emits_activity(self, db_session, actor_id, tenant_id):
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("libs.core.activity.record_activity_with_outbox") as mock_emit:
            mock_emit.return_value = AsyncMock()

            signal = await service.create(
                SignalCreateDTO(name="test", signal_type="alpha", frequency="daily"),
                parent_id=uuid4()
            )

            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            envelope = call_kwargs["envelope"]

            assert envelope.action == "signal.created"
            assert envelope.actor_principal_id == actor_id
            assert envelope.resource_type == "signal"
            assert "signal_type" in envelope.payload

    @pytest.mark.asyncio
    async def test_update_emits_changes(self, db_session, existing_signal):
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("libs.core.activity.record_activity_with_outbox") as mock_emit:
            await service.update(
                existing_signal.id,
                SignalUpdateDTO(lookback_days=30)
            )

            envelope = mock_emit.call_args.kwargs["envelope"]
            assert envelope.action == "signal.updated"
            assert "changes" in envelope.payload
            assert "lookback_days" in envelope.payload["changes"]

    @pytest.mark.asyncio
    async def test_delete_emits_activity(self, db_session, existing_signal):
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("libs.core.activity.record_activity_with_outbox") as mock_emit:
            await service.delete(existing_signal.id)

            envelope = mock_emit.call_args.kwargs["envelope"]
            assert envelope.action == "signal.deleted"
```

## Integration Testing (with outbox)

```python
@pytest.mark.asyncio
async def test_activity_reaches_outbox(self, db_session):
    service = SignalService(db_session, actor_id, tenant_id)

    signal = await service.create(dto, parent_id)
    await db_session.commit()

    # Check outbox has entry
    outbox_entry = await db_session.execute(
        select(OutboxEntry).where(OutboxEntry.payload["resource_id"].astext == str(signal.resource_id))
    )
    entry = outbox_entry.scalar_one()

    assert entry is not None
    assert entry.payload["action"] == "signal.created"
```

## Testing Correlation IDs

```python
@pytest.mark.asyncio
async def test_workflow_uses_same_correlation_id(self):
    correlation_id = uuid4()

    activities = []
    with patch("libs.core.activity.record_activity_with_outbox") as mock:
        mock.side_effect = lambda **kwargs: activities.append(kwargs["envelope"])

        await promotion_workflow(correlation_id)

    # All activities should share correlation_id
    for activity in activities:
        assert activity.correlation_id == correlation_id
```

## Idempotency Testing

```python
@pytest.mark.asyncio
async def test_duplicate_activity_rejected(self, db_session):
    correlation_id = uuid4()
    envelope = ActivityEnvelope(
        action="signal.created",
        correlation_id=correlation_id,
        ...
    )

    # First call succeeds
    activity1 = await record_activity_with_outbox(session=db_session, envelope=envelope)
    assert activity1 is not None

    # Duplicate is rejected (idempotent)
    activity2 = await record_activity_with_outbox(session=db_session, envelope=envelope)
    assert activity2.id == activity1.id  # Same activity returned
```
