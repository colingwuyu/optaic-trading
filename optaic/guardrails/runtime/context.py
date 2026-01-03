"""Runtime context for guardrails validation."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GuardrailsContext(BaseModel):
    """Contextual information for guardrails validation.

    This context is passed to the engine and validators to determine
    enforcement policies and validate rules that depend on the environment.
    """

    tenant_id: UUID = Field(..., description="ID of the tenant")
    actor_principal_id: UUID = Field(
        ..., description="ID of the principal performing the action"
    )
    space_kind: Optional[str] = Field(
        None, description="Kind of the space (e.g., personal, team, system)"
    )
    subspace_kind: Optional[str] = Field(
        None, description="Kind of the subspace (e.g., official, staging)"
    )
    action: str = Field(
        ..., description="The action being performed (e.g., create, update, promote)"
    )
    correlation_id: Optional[UUID] = Field(
        None, description="Correlation ID for tracing"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="Additional context data"
    )
