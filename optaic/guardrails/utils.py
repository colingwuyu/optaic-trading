"""Utility functions for canonical JSON serialization and hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from optaic.guardrails.contracts.base import ContractRef


def canonical_dumps(obj: Any) -> str:
    """Serialize object to a canonical JSON string.

    Produces a deterministic JSON representation with:
    - Sorted keys
    - No extra whitespace
    - Consistent separators

    Args:
        obj: Object to serialize. Pydantic models are converted via model_dump().

    Returns:
        Canonical JSON string.
    """
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_str(s: str) -> str:
    """Compute SHA-256 hex digest of a string.

    Args:
        s: Input string.

    Returns:
        64-character lowercase hex digest.
    """
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def contract_hash(ref: "ContractRef", config_json: str) -> str:
    """Compute deterministic hash for a contract reference + config.

    The hash is computed from a canonical JSON representation of:
    - contract_kind
    - contract_name
    - version
    - json_schema
    - config_json

    Args:
        ref: Contract reference with kind/name/version/schema.
        config_json: JSON string of the contract configuration.

    Returns:
        SHA-256 hex digest of the canonical representation.
    """
    # Import here to avoid circular import
    from optaic.guardrails.contracts.base import ContractRef

    if not isinstance(ref, ContractRef):
        raise TypeError(f"Expected ContractRef, got {type(ref).__name__}")

    payload = {
        "contract_kind": ref.contract_kind,
        "contract_name": ref.contract_name,
        "version": ref.version,
        "json_schema": ref.json_schema,
        "config_json": config_json,
    }
    return sha256_str(canonical_dumps(payload))
