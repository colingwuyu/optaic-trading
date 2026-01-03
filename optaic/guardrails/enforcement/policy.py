"""Enforcement policy for guardrails.

Determines the effective enforcement level based on:
- Subspace kind (official vs staging)
- Action being performed
- Contract's enforcement hint
"""

from __future__ import annotations

from typing import Literal


def compute_effective_enforcement(
    subspace_kind: str,
    action: str,
    hint: Literal["warn", "block"],
) -> Literal["warn", "block"]:
    """Compute the effective enforcement level for a validation.

    Policy v0:
    - If subspace_kind == "official" => always "block"
    - Otherwise => "warn" unless hint == "block" (then "block")

    Args:
        subspace_kind: The kind of subspace ("official", "staging", etc.).
        action: The action being performed (e.g., "create", "update", "promote").
        hint: The contract's suggested enforcement level.

    Returns:
        "warn" or "block" indicating the effective enforcement level.
    """
    # Official subspace always enforces blocking
    if subspace_kind == "official":
        return "block"

    # Staging subspace fails open (warn) even if hint is block
    if subspace_kind == "staging":
        return "warn"

    # For other subspaces (custom, etc.), respect the hint
    if hint == "block":
        return "block"

    return "warn"
