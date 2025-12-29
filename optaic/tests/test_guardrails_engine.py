"""Unit tests for GuardrailsEngine."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from optaic.guardrails.contracts.base import ContractBundle, ContractInstance, ContractRef
from optaic.guardrails.runtime.context import GuardrailsContext
from optaic.guardrails.runtime.engine import GuardrailsBlocked, GuardrailsEngine
from optaic.guardrails.validators.base import ValidationIssue


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.validate_bundle.return_value = []
    return registry


@pytest.fixture
def engine(mock_registry):
    return GuardrailsEngine(registry=mock_registry)


@pytest.fixture
def context():
    return GuardrailsContext(
        tenant_id=uuid4(),
        actor_principal_id=uuid4(),
        action="update",
        space_kind="team",
        subspace_kind="official",
    )


@pytest.fixture
def resource_id():
    return str(uuid4())

@pytest.fixture
def sample_bundle(resource_id):
    return ContractBundle(
        bundle_id=str(uuid4()),
        resource_id=resource_id,
        created_by="user",
        contracts=[
            ContractInstance(
                ref=ContractRef(contract_kind="test", contract_name="c1", version="1"),
                config_json="{}",
                contract_hash="hash",
                enforcement_hint="block",
            )
        ],
    )


@pytest.mark.asyncio
async def test_validate_no_bundle_returns_ok_report(engine, mock_db, context, resource_id):
    """Test that if no bundle exists, we get a passing report."""
    with patch("optaic.guardrails.storage.ContractBundleStore.get_active_bundle", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        
        with patch("optaic.guardrails.runtime.engine.record_activity_with_outbox", new_callable=AsyncMock) as mock_emit:
            with patch("optaic.guardrails.storage.ValidationReportStore.insert_report", new_callable=AsyncMock):
                
                report = await engine.validate_at_gate(
                    db=mock_db,
                    scope="resource",
                    target_id=str(uuid4()),
                    resource_id=resource_id,
                    context=context,
                    target_snapshot={},
                )

                assert report.ok is True
                assert report.enforced_as == "warn"
                mock_emit.assert_called_once()
                args, _ = mock_emit.call_args
                envelope = args[1]
                assert envelope.action == "guardrails.validated"


@pytest.mark.asyncio
async def test_validate_official_blocks_on_error(engine, mock_db, context, sample_bundle, mock_registry, resource_id):
    """Test that errors in 'official' subspace with 'block' hint raise GuardrailsBlocked."""
    # Setup bundle
    with patch("optaic.guardrails.storage.ContractBundleStore.get_active_bundle", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = sample_bundle
        
        # Setup validation failure
        mock_registry.validate_bundle.return_value = [
            ValidationIssue(code="ERR", severity="error", message="Fail", path=".")
        ]
        
        with patch("optaic.guardrails.runtime.engine.record_activity_with_outbox", new_callable=AsyncMock) as mock_emit:
             with patch("optaic.guardrails.storage.ValidationReportStore.insert_report", new_callable=AsyncMock):
                
                with pytest.raises(GuardrailsBlocked) as exc:
                    await engine.validate_at_gate(
                        db=mock_db,
                        scope="resource",
                        target_id=str(uuid4()),
                        resource_id=resource_id,
                        context=context,  # subspace='official'
                        target_snapshot={},
                    )
                
                assert "1 issues found" in str(exc.value)
                
                # Verify 'blocked' event emitted
                mock_emit.assert_called_once()
                envelope = mock_emit.call_args[0][1]
                assert envelope.action == "guardrails.blocked"


@pytest.mark.asyncio
async def test_validate_staging_warns_on_error(engine, mock_db, sample_bundle, mock_registry, resource_id):
    """Test that errors in 'staging' subspace DO NOT block contract with 'block' hint."""
    context = GuardrailsContext(
        tenant_id=uuid4(),
        actor_principal_id=uuid4(),
        action="update",
        space_kind="team",
        subspace_kind="staging", # Staging
    )

    with patch("optaic.guardrails.storage.ContractBundleStore.get_active_bundle", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = sample_bundle # Has hint='block'
        
        # Setup validation failure
        mock_registry.validate_bundle.return_value = [
            ValidationIssue(code="ERR", severity="error", message="Fail", path=".")
        ]
        
        with patch("optaic.guardrails.runtime.engine.record_activity_with_outbox", new_callable=AsyncMock) as mock_emit:
             with patch("optaic.guardrails.storage.ValidationReportStore.insert_report", new_callable=AsyncMock):
                
                report = await engine.validate_at_gate(
                    db=mock_db,
                    scope="resource",
                    target_id=str(uuid4()),
                    resource_id=resource_id,
                    context=context,
                    target_snapshot={},
                )
                
                # Should not raise exception
                assert report.ok is False
                assert report.enforced_as == "warn" # Policy overrides block hint in staging
                
                # Verify 'validated' event emitted (not blocked)
                mock_emit.assert_called_once()
                envelope = mock_emit.call_args[0][1]
                assert envelope.action == "guardrails.validated"
