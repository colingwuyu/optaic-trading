# Guardrails Integration Test Patterns

## Test Validation at Lifecycle Gates

```python
import pytest
from unittest.mock import patch, AsyncMock

class TestGuardrailsIntegration:

    @pytest.mark.asyncio
    async def test_create_calls_guardrails_validation(self, db_session):
        """Verify create gate triggers guardrails validation."""
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("optaic.guardrails.GuardrailsEngine.validate_at_gate") as mock:
            mock.return_value = ValidationReport(ok=True, enforced_as="warn")

            await service.create(dto, parent_id)

            mock.assert_called_once()
            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["gate"] == "create"
            assert call_kwargs["resource_id"] is not None

    @pytest.mark.asyncio
    async def test_update_calls_guardrails_validation(self, db_session, existing):
        """Verify update gate triggers guardrails validation."""
        service = SignalService(db_session, actor_id, tenant_id)

        with patch("optaic.guardrails.GuardrailsEngine.validate_at_gate") as mock:
            mock.return_value = ValidationReport(ok=True)

            await service.update(existing.id, update_dto)

            mock.assert_called_once()
            assert mock.call_args.kwargs["gate"] == "update"
```

## Test Enforcement Policy

```python
@pytest.mark.asyncio
async def test_blocks_on_official_validation_failure(self, db_session):
    """Verify official subspace blocks on validation errors."""
    service = SignalService(db_session, actor_id, tenant_id)

    with patch("optaic.guardrails.GuardrailsEngine.validate_at_gate") as mock:
        mock.return_value = ValidationReport(
            ok=False,
            enforced_as="block",
            issues=[ValidationIssue(severity="error", message="fail")]
        )

        with pytest.raises(GuardrailsBlocked) as exc:
            await service.create(dto, parent_id)

        assert exc.value.report.enforced_as == "block"

@pytest.mark.asyncio
async def test_warns_on_staging_validation_failure(self, db_session):
    """Verify staging subspace warns but proceeds on validation errors."""
    service = SignalService(db_session, actor_id, tenant_id)

    with patch("optaic.guardrails.GuardrailsEngine.validate_at_gate") as mock:
        mock.return_value = ValidationReport(
            ok=False,
            enforced_as="warn",
            issues=[ValidationIssue(severity="error", message="fail")]
        )

        # Should NOT raise, just warn
        result = await service.create(dto, parent_id)
        assert result is not None
```

## Test Report Storage

```python
@pytest.mark.asyncio
async def test_validation_report_persisted(self, db_session):
    """Verify validation reports are stored for audit."""
    service = SignalService(db_session, actor_id, tenant_id)

    await service.create(dto, parent_id)
    await db_session.commit()

    # Query for report
    result = await db_session.execute(
        select(ValidationReport).where(ValidationReport.scope == "resource")
    )
    report = result.scalar_one()

    assert report is not None
    assert report.target_id is not None
```

## Test Activity Emission for Guardrails

```python
@pytest.mark.asyncio
async def test_guardrails_emits_activity(self, db_session):
    """Verify guardrails.validated activity is emitted."""
    with patch("libs.core.activity.record_activity_with_outbox") as mock:
        await service.create(dto, parent_id)

        # Find guardrails activity
        calls = [c for c in mock.call_args_list
                 if c.kwargs["envelope"].action.startswith("guardrails.")]
        assert len(calls) >= 1
        assert calls[0].kwargs["envelope"].action == "guardrails.validated"
```
