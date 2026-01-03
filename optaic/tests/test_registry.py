"""Tests for ContractRegistry and built-in validators.

Acceptance tests:
- test_registry_register_and_get_schema
- test_jsonschema_validator_ok
- test_jsonschema_validator_returns_issue_on_missing_required_field
- test_validate_bundle_runs_default_validator
- test_unknown_contract_kind_raises_clear_error
"""

from __future__ import annotations

import pytest

from optaic.guardrails import (
    ContractRef,
    ContractInstance,
    ContractBundle,
    ContractRegistry,
    UnknownContractKindError,
    UnknownValidatorError,
    JsonSchemaValidator,
    NoOpValidator,
    contract_hash,
)


# =============================================================================
# Registry Tests
# =============================================================================


def test_registry_register_and_get_schema() -> None:
    """Registry can register and retrieve contract schemas."""
    registry = ContractRegistry()

    schema = {
        "type": "object",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["columns"],
    }

    registry.register_contract_kind(
        kind="schema",
        version="1.0.0",
        json_schema=schema,
        default_validator="jsonschema",
    )

    # Retrieve the schema
    retrieved = registry.get_contract_schema("schema", "1.0.0")
    assert retrieved == schema

    # Check default validator
    assert registry.get_default_validator("schema", "1.0.0") == "jsonschema"


def test_unknown_contract_kind_raises_clear_error() -> None:
    """Unknown contract kind raises UnknownContractKindError with helpful message."""
    registry = ContractRegistry()

    with pytest.raises(UnknownContractKindError) as exc_info:
        registry.get_contract_schema("nonexistent", "1.0.0")

    assert "nonexistent" in str(exc_info.value)
    assert "register_contract_kind" in str(exc_info.value)


def test_unknown_validator_raises_clear_error() -> None:
    """Unknown validator raises UnknownValidatorError with helpful message."""
    registry = ContractRegistry()

    # Register a contract kind with a non-existent validator
    registry.register_contract_kind(
        kind="test",
        version="1.0.0",
        json_schema={"type": "object"},
        default_validator="nonexistent_validator",
    )

    ref = ContractRef(
        contract_kind="test",
        contract_name="test_contract",
        version="1.0.0",
    )
    instance = ContractInstance(
        ref=ref,
        config_json="{}",
        contract_hash=contract_hash(ref, "{}"),
    )

    with pytest.raises(UnknownValidatorError) as exc_info:
        registry.validate_contract_config(instance)

    assert "nonexistent_validator" in str(exc_info.value)
    assert "register_validator" in str(exc_info.value)


# =============================================================================
# JsonSchemaValidator Tests
# =============================================================================


def test_jsonschema_validator_ok() -> None:
    """JsonSchemaValidator returns no issues for valid config."""
    registry = ContractRegistry()
    registry.register_validator("jsonschema", JsonSchemaValidator)

    schema = {
        "type": "object",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
            "nullable": {"type": "boolean"},
        },
        "required": ["columns"],
    }

    registry.register_contract_kind(
        kind="schema",
        version="1.0.0",
        json_schema=schema,
    )

    ref = ContractRef(
        contract_kind="schema",
        contract_name="dataset_columns",
        version="1.0.0",
    )
    instance = ContractInstance(
        ref=ref,
        config_json='{"columns": ["id", "name", "value"], "nullable": false}',
        contract_hash=contract_hash(
            ref, '{"columns": ["id", "name", "value"], "nullable": false}'
        ),
    )

    # Validate config
    issues = registry.validate_contract_config(instance)
    assert issues == []


def test_jsonschema_validator_returns_issue_on_missing_required_field() -> None:
    """JsonSchemaValidator returns issue when required field is missing."""
    registry = ContractRegistry()
    registry.register_validator("jsonschema", JsonSchemaValidator)

    schema = {
        "type": "object",
        "properties": {
            "columns": {"type": "array", "items": {"type": "string"}},
            "table_name": {"type": "string"},
        },
        "required": ["columns", "table_name"],
    }

    registry.register_contract_kind(
        kind="schema",
        version="1.0.0",
        json_schema=schema,
    )

    ref = ContractRef(
        contract_kind="schema",
        contract_name="dataset_columns",
        version="1.0.0",
    )
    # Missing "table_name" required field
    instance = ContractInstance(
        ref=ref,
        config_json='{"columns": ["id", "name"]}',
        contract_hash=contract_hash(ref, '{"columns": ["id", "name"]}'),
    )

    issues = registry.validate_contract_config(instance)

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "schema.invalid"
    assert "table_name" in issues[0].message
    assert "required" in issues[0].message.lower()


def test_jsonschema_validator_type_error() -> None:
    """JsonSchemaValidator returns issue when type is wrong."""
    registry = ContractRegistry()
    registry.register_validator("jsonschema", JsonSchemaValidator)

    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
        },
    }

    registry.register_contract_kind(
        kind="metric",
        version="1.0.0",
        json_schema=schema,
    )

    ref = ContractRef(
        contract_kind="metric",
        contract_name="row_count",
        version="1.0.0",
    )
    # count is string instead of integer
    instance = ContractInstance(
        ref=ref,
        config_json='{"count": "not_an_integer"}',
        contract_hash=contract_hash(ref, '{"count": "not_an_integer"}'),
    )

    issues = registry.validate_contract_config(instance)

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "schema.invalid"
    assert "$.count" in (issues[0].path or "")


# =============================================================================
# Bundle Validation Tests
# =============================================================================


def test_validate_bundle_runs_default_validator() -> None:
    """validate_bundle runs the default validator for each contract."""
    registry = ContractRegistry()
    registry.register_validator("jsonschema", JsonSchemaValidator)

    # Register two contract kinds
    registry.register_contract_kind(
        kind="schema",
        version="1.0.0",
        json_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    registry.register_contract_kind(
        kind="invariant",
        version="1.0.0",
        json_schema={
            "type": "object",
            "properties": {"min_value": {"type": "integer"}},
        },
    )

    # Create contracts
    ref1 = ContractRef(
        contract_kind="schema", contract_name="test_schema", version="1.0.0"
    )
    ref2 = ContractRef(
        contract_kind="invariant", contract_name="test_invariant", version="1.0.0"
    )

    instance1 = ContractInstance(
        ref=ref1,
        config_json="{}",  # Missing required "name"
        contract_hash=contract_hash(ref1, "{}"),
    )
    instance2 = ContractInstance(
        ref=ref2,
        config_json='{"min_value": 10}',  # Valid
        contract_hash=contract_hash(ref2, '{"min_value": 10}'),
    )

    bundle = ContractBundle(
        bundle_id="test-bundle",
        resource_id="resource-123",
        created_by="test",
        contracts=[instance1, instance2],
    )

    # Target snapshot that doesn't have required "name"
    target = {}

    context = {"subspace": "staging", "action": "create"}
    issues = registry.validate_bundle(bundle, context, target)

    # Should have one issue from the first contract (missing name)
    assert len(issues) == 1
    assert "name" in issues[0].message


def test_validate_bundle_empty() -> None:
    """validate_bundle with empty contracts list returns no issues."""
    registry = ContractRegistry()

    bundle = ContractBundle(
        bundle_id="empty-bundle",
        resource_id="resource-456",
        created_by="test",
        contracts=[],
    )

    issues = registry.validate_bundle(bundle, {}, {})
    assert issues == []


# =============================================================================
# NoOpValidator Tests
# =============================================================================


def test_noop_validator_always_empty() -> None:
    """NoOpValidator always returns empty list."""
    registry = ContractRegistry()
    registry.register_validator("noop", NoOpValidator)
    registry.register_contract_kind(
        kind="placeholder",
        version="1.0.0",
        json_schema={"type": "object"},
        default_validator="noop",
    )

    ref = ContractRef(
        contract_kind="placeholder",
        contract_name="test",
        version="1.0.0",
    )
    instance = ContractInstance(
        ref=ref,
        config_json='{"anything": "goes"}',
        contract_hash=contract_hash(ref, '{"anything": "goes"}'),
    )

    issues = registry.validate_contract_config(instance)
    assert issues == []


# =============================================================================
# Validator Plugin Tests
# =============================================================================


def test_registry_supports_custom_validators() -> None:
    """Registry supports registering custom validators."""
    from optaic.guardrails.validators.base import ContractValidator, ValidationIssue
    from typing import Any

    class AlwaysFailValidator(ContractValidator):
        @property
        def name(self) -> str:
            return "always_fail"

        def validate(
            self,
            context: dict[str, Any],
            bundle: ContractBundle,
            contract_instance: ContractInstance,
            target_snapshot: Any,
        ) -> list[ValidationIssue]:
            return [
                ValidationIssue(
                    severity="error",
                    code="always.fail",
                    message="This validator always fails",
                )
            ]

    registry = ContractRegistry()
    registry.register_validator("always_fail", AlwaysFailValidator)
    registry.register_contract_kind(
        kind="strict",
        version="1.0.0",
        json_schema={},
        default_validator="always_fail",
    )

    ref = ContractRef(contract_kind="strict", contract_name="test", version="1.0.0")
    instance = ContractInstance(
        ref=ref,
        config_json="{}",
        contract_hash=contract_hash(ref, "{}"),
    )

    issues = registry.validate_contract_config(instance)

    assert len(issues) == 1
    assert issues[0].code == "always.fail"
