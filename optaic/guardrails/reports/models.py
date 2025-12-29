"""Report models for the guardrails framework."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from optaic.guardrails.validators.base import ValidationIssue


class ValidationReport(BaseModel):
    """Full validation report for a single validation run.

    Contains all issues found, enforcement decision, and audit metadata.
    """

    report_id: str = Field(
        ...,
        description="Unique identifier for this report",
    )
    scope: Literal["resource", "run", "promotion", "merge"] = Field(
        ...,
        description="Scope of validation (what triggered it)",
    )
    target_id: str = Field(
        ...,
        description="ID of the target being validated (resource, run, etc.)",
    )
    ok: bool = Field(
        ...,
        description="Whether validation passed (no blocking errors)",
    )
    enforced_as: Literal["warn", "block"] = Field(
        ...,
        description="Actual enforcement level applied",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="All validation issues found",
    )
    contract_hashes: list[str] = Field(
        default_factory=list,
        description="Hashes of all contracts that were validated",
    )
    created_by: str = Field(
        ...,
        description="User or system that triggered validation",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when validation was performed",
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Optional ID to correlate with activity events",
    )
