"""Built-in validators for the guardrails framework."""

from __future__ import annotations

import json
from typing import Any

from optaic.guardrails.contracts.base import ContractBundle, ContractInstance
from optaic.guardrails.validators.base import ContractValidator, ValidationIssue


class JsonSchemaValidator(ContractValidator):
    """Validator that uses JSON Schema to validate contract configs.

    Validates the contract_instance.config_json against the schema
    from contract_instance.ref.schema_json or from context["schema"].
    """

    @property
    def name(self) -> str:
        """Unique name identifying this validator."""
        return "jsonschema"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        """Validate using JSON Schema.

        For config validation (mode="config_validation"), validates target_snapshot
        against the schema in context["schema"].

        For runtime validation, validates target_snapshot against the contract's
        schema_json.

        Args:
            context: Must contain "schema" key with JSON Schema dict.
            bundle: The contract bundle (not used directly).
            contract_instance: The contract instance being validated.
            target_snapshot: The data to validate (parsed JSON).

        Returns:
            List of validation issues.
        """
        try:
            from jsonschema import Draft7Validator
        except ImportError:
            return [
                ValidationIssue(
                    severity="error",
                    code="validator.missing_dependency",
                    message="jsonschema package is required. Install with: pip install optaic[guardrails]",
                )
            ]

        # Get schema from context or contract ref
        schema = context.get("schema")
        if schema is None:
            # Fall back to contract's json_schema
            schema_str = contract_instance.ref.json_schema
            if schema_str and schema_str != "{}":
                schema = json.loads(schema_str)
            else:
                # No schema to validate against
                return []

        # Validate target_snapshot against schema
        issues: list[ValidationIssue] = []
        validator = Draft7Validator(schema)

        for error in validator.iter_errors(target_snapshot):
            path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else None
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="schema.invalid",
                    message=error.message,
                    path=f"$.{path}" if path else "$",
                    meta={
                        "schema_path": list(error.schema_path),
                        "validator": error.validator,
                    },
                )
            )

        return issues


class NoOpValidator(ContractValidator):
    """A no-op validator that always returns no issues.

    Useful for contracts that don't require runtime validation,
    or as a placeholder during development.
    """

    @property
    def name(self) -> str:
        """Unique name identifying this validator."""
        return "noop"

    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        """Always returns an empty list (no issues).

        Args:
            context: Ignored.
            bundle: Ignored.
            contract_instance: Ignored.
            target_snapshot: Ignored.

        Returns:
            Empty list.
        """
        return []
