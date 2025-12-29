"""Base validator classes for the guardrails framework."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from optaic.guardrails.contracts.base import ContractBundle, ContractInstance


class ValidationIssue(BaseModel):
    """A single validation issue found during contract validation.

    Represents either a warning or an error with contextual information.
    """

    severity: Literal["warning", "error"] = Field(
        ...,
        description="Severity level of the issue",
    )
    code: str = Field(
        ...,
        description="Machine-readable error code (e.g., 'SCHEMA_MISMATCH')",
    )
    message: str = Field(
        ...,
        description="Human-readable description of the issue",
    )
    path: Optional[str] = Field(
        default=None,
        description="JSONPath or field path where the issue occurred",
    )
    meta: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional metadata about the issue",
    )


class ContractValidator(ABC):
    """Abstract base class for contract validators.

    Validators check contract instances against target data snapshots.
    Each validator specializes in a specific contract kind.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifying this validator."""
        ...

    @abstractmethod
    def validate(
        self,
        context: dict[str, Any],
        bundle: ContractBundle,
        contract_instance: ContractInstance,
        target_snapshot: Any,
    ) -> list[ValidationIssue]:
        """Validate a contract instance against a target snapshot.

        Args:
            context: Contextual information (e.g., user, action, subspace).
            bundle: The contract bundle containing this instance.
            contract_instance: The specific contract instance to validate.
            target_snapshot: The data snapshot to validate against.

        Returns:
            List of validation issues found. Empty list means validation passed.
        """
        ...
