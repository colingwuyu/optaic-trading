"""Contract registry for managing contract kinds and validators."""

from __future__ import annotations

import json
from typing import Any, Type

from optaic.guardrails.contracts.base import ContractBundle, ContractInstance
from optaic.guardrails.validators.base import ContractValidator, ValidationIssue


class UnknownContractKindError(Exception):
    """Raised when a contract kind is not registered."""

    def __init__(self, kind: str, version: str | None = None) -> None:
        self.kind = kind
        self.version = version
        if version:
            msg = f"Unknown contract kind '{kind}' version '{version}'. Register it first with register_contract_kind()."
        else:
            msg = f"Unknown contract kind '{kind}'. Register it first with register_contract_kind()."
        super().__init__(msg)


class UnknownValidatorError(Exception):
    """Raised when a validator is not registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Unknown validator '{name}'. Register it first with register_validator()."
        )


class ContractRegistry:
    """Registry for contract kinds and validators.

    Manages contract schemas and validators, supporting plug-in validators.

    Example:
        registry = ContractRegistry()
        registry.register_contract_kind(
            kind="schema",
            version="1.0.0",
            schema_json={"type": "object", "properties": {...}},
        )
        issues = registry.validate_bundle(bundle, context, target_snapshot)
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        # {(kind, version): {"schema": dict, "default_validator": str}}
        self._contract_kinds: dict[tuple[str, str], dict[str, Any]] = {}
        # {name: validator_class}
        self._validators: dict[str, Type[ContractValidator]] = {}

    def register_contract_kind(
        self,
        kind: str,
        version: str,
        json_schema: dict[str, Any],
        default_validator: str = "jsonschema",
    ) -> None:
        """Register a contract kind with its schema.

        Args:
            kind: Category of the contract (e.g., 'schema', 'invariant').
            version: Semantic version (e.g., '1.0.0').
            json_schema: JSON Schema dict for validating contract configs.
            default_validator: Name of the default validator to use.
        """
        key = (kind, version)
        self._contract_kinds[key] = {
            "schema": json_schema,
            "default_validator": default_validator,
        }

    def register_validator(
        self,
        name: str,
        validator_cls: Type[ContractValidator],
    ) -> None:
        """Register a validator class.

        Args:
            name: Unique name for the validator.
            validator_cls: Validator class (must implement ContractValidator).
        """
        self._validators[name] = validator_cls

    def get_contract_schema(self, kind: str, version: str) -> dict[str, Any]:
        """Get the JSON Schema for a contract kind.

        Args:
            kind: Contract kind.
            version: Contract version.

        Returns:
            JSON Schema dict.

        Raises:
            UnknownContractKindError: If the contract kind is not registered.
        """
        key = (kind, version)
        if key not in self._contract_kinds:
            raise UnknownContractKindError(kind, version)
        return self._contract_kinds[key]["schema"]

    def get_default_validator(self, kind: str, version: str) -> str:
        """Get the default validator name for a contract kind.

        Args:
            kind: Contract kind.
            version: Contract version.

        Returns:
            Validator name.

        Raises:
            UnknownContractKindError: If the contract kind is not registered.
        """
        key = (kind, version)
        if key not in self._contract_kinds:
            raise UnknownContractKindError(kind, version)
        return self._contract_kinds[key]["default_validator"]

    def _get_validator_instance(self, name: str) -> ContractValidator:
        """Get a validator instance by name.

        Args:
            name: Validator name.

        Returns:
            Validator instance.

        Raises:
            UnknownValidatorError: If the validator is not registered.
        """
        if name not in self._validators:
            raise UnknownValidatorError(name)
        return self._validators[name]()

    def validate_contract_config(
        self,
        contract_instance: ContractInstance,
    ) -> list[ValidationIssue]:
        """Validate a contract instance's config against its schema.

        Uses the default validator for the contract kind.

        Args:
            contract_instance: The contract instance to validate.

        Returns:
            List of validation issues (empty if valid).

        Raises:
            UnknownContractKindError: If the contract kind is not registered.
            UnknownValidatorError: If the default validator is not registered.
        """
        ref = contract_instance.ref
        validator_name = self.get_default_validator(ref.contract_kind, ref.version)
        validator = self._get_validator_instance(validator_name)

        # For config validation, we pass the schema as context
        # and the config as target_snapshot
        context = {
            "schema": self.get_contract_schema(ref.contract_kind, ref.version),
            "mode": "config_validation",
        }

        # Parse config_json if it's a string
        config = contract_instance.config_json
        if isinstance(config, str):
            config = json.loads(config)

        # Create a minimal bundle for the validator
        bundle = ContractBundle(
            bundle_id="config-validation",
            resource_id="config-validation",
            created_by="system",
            contracts=[contract_instance],
        )

        return validator.validate(context, bundle, contract_instance, config)

    def validate_bundle(
        self,
        bundle: ContractBundle,
        context: dict[str, Any],
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        """Validate all contracts in a bundle against a target snapshot.

        Runs the default validator for each contract kind.

        Args:
            bundle: The contract bundle to validate.
            context: Contextual information (user, action, subspace, etc.).
            target_snapshot: The data snapshot to validate against.

        Returns:
            List of all validation issues from all contracts.

        Raises:
            UnknownContractKindError: If any contract kind is not registered.
            UnknownValidatorError: If any default validator is not registered.
        """
        all_issues: list[ValidationIssue] = []

        for contract_instance in bundle.contracts:
            ref = contract_instance.ref
            validator_name = self.get_default_validator(ref.contract_kind, ref.version)
            validator = self._get_validator_instance(validator_name)

            # Enrich context with schema for this contract
            enriched_context = {
                **context,
                "schema": self.get_contract_schema(ref.contract_kind, ref.version),
            }

            issues = validator.validate(
                enriched_context, bundle, contract_instance, target_snapshot
            )
            all_issues.extend(issues)

        return all_issues


# Global default registry instance
_default_registry: ContractRegistry | None = None


def get_default_registry() -> ContractRegistry:
    """Get or create the default global registry.

    Returns:
        The default ContractRegistry instance.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ContractRegistry()
        # Register built-in validators
        from optaic.guardrails.validators.builtins import (
            JsonSchemaValidator,
            NoOpValidator,
        )

        _default_registry.register_validator("jsonschema", JsonSchemaValidator)
        _default_registry.register_validator("noop", NoOpValidator)
    return _default_registry
