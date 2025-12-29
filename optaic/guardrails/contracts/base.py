"""Base contract models for the guardrails framework."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ContractRef(BaseModel):
    """Reference to a contract definition.

    Identifies a specific contract kind, name, version, and its schema.
    """

    contract_kind: str = Field(
        ...,
        description="Category of the contract (e.g., 'schema', 'invariant', 'metric')",
    )
    contract_name: str = Field(
        ...,
        description="Unique name of the contract within its kind",
    )
    version: str = Field(
        ...,
        description="Semantic version of the contract (e.g., '1.0.0')",
    )
    json_schema: str = Field(
        default="{}",
        description="JSON schema defining the contract's configuration structure",
    )

    model_config = {"frozen": True}


class ContractInstance(BaseModel):
    """A bound contract with specific configuration.

    Represents a contract reference bound to a specific configuration,
    with a pre-computed hash for integrity checking.
    """

    ref: ContractRef = Field(
        ...,
        description="Reference to the contract definition",
    )
    config_json: str = Field(
        default="{}",
        description="JSON configuration for this contract instance",
    )
    contract_hash: str = Field(
        ...,
        description="SHA-256 hash of the contract ref + config for integrity",
    )
    enforcement_hint: Literal["warn", "block"] = Field(
        default="warn",
        description="Suggested enforcement level (may be overridden by policy)",
    )

    model_config = {"frozen": True}


class ContractBundle(BaseModel):
    """A collection of contracts associated with a resource.

    Bundles multiple contract instances together for a resource,
    optionally tied to a specific resource version.
    """

    bundle_id: str = Field(
        ...,
        description="Unique identifier for this bundle",
    )
    resource_id: str = Field(
        ...,
        description="ID of the resource this bundle applies to",
    )
    resource_version_id: Optional[str] = Field(
        default=None,
        description="Optional specific version of the resource",
    )
    created_by: str = Field(
        ...,
        description="User or system that created this bundle",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the bundle was created",
    )
    contracts: list[ContractInstance] = Field(
        default_factory=list,
        description="List of contract instances in this bundle",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional notes about this bundle",
    )
