"""Guardrails framework for contract-based validation."""

from optaic.guardrails.contracts.base import (
    ContractRef,
    ContractInstance,
    ContractBundle,
)
from optaic.guardrails.contracts.registry import (
    ContractRegistry,
    UnknownContractKindError,
    UnknownValidatorError,
    get_default_registry,
)
from optaic.guardrails.validators.base import (
    ValidationIssue,
    ContractValidator,
)
from optaic.guardrails.validators.builtins import (
    JsonSchemaValidator,
    NoOpValidator,
)
from optaic.guardrails.reports.models import ValidationReport
from optaic.guardrails.enforcement.policy import compute_effective_enforcement
from optaic.guardrails.utils import canonical_dumps, sha256_str, contract_hash

__all__ = [
    # Contracts
    "ContractRef",
    "ContractInstance",
    "ContractBundle",
    # Registry
    "ContractRegistry",
    "UnknownContractKindError",
    "UnknownValidatorError",
    "get_default_registry",
    # Validators
    "ValidationIssue",
    "ContractValidator",
    "JsonSchemaValidator",
    "NoOpValidator",
    # Reports
    "ValidationReport",
    # Enforcement
    "compute_effective_enforcement",
    # Utils
    "canonical_dumps",
    "sha256_str",
    "contract_hash",
]
