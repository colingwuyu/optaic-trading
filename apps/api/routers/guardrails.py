"""Guardrails API endpoints for admin operations.

Provides endpoints to manage contract bundles and view validation reports.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db
from optaic.guardrails.contracts.base import ContractBundle
from optaic.guardrails.reports.models import ValidationReport
from optaic.guardrails.storage import ContractBundleStore, ValidationReportStore

router = APIRouter(prefix="/guardrails", tags=["Guardrails"])


# =============================================================================
# Request/Response Schemas
# =============================================================================


class BundleCreateRequest(BaseModel):
    """Request body for creating/replacing a contract bundle."""

    bundle: ContractBundle = Field(..., description="The contract bundle to set")


class BundleResponse(BaseModel):
    """Response containing a contract bundle."""

    bundle: Optional[ContractBundle] = Field(
        None, description="The active bundle, if any"
    )


class ReportsListResponse(BaseModel):
    """Response containing a list of validation reports."""

    reports: list[ValidationReport] = Field(
        default_factory=list, description="List of validation reports"
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/resources/{resource_id}/bundle",
    response_model=BundleResponse,
    summary="Get active contract bundle",
    description="Retrieve the currently active contract bundle for a resource.",
)
async def get_resource_bundle(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    """Get the active contract bundle for a resource."""
    bundle = await ContractBundleStore.get_active_bundle(db, resource_id)
    return BundleResponse(bundle=bundle)


@router.put(
    "/resources/{resource_id}/bundle",
    response_model=BundleResponse,
    summary="Set active contract bundle",
    description="Replace the active contract bundle for a resource. Any existing active bundle will be deactivated.",
)
async def put_resource_bundle(
    resource_id: str,
    request: BundleCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    """Replace the active contract bundle for a resource."""
    bundle = request.bundle

    # Ensure resource_id in path matches bundle
    if bundle.resource_id != resource_id:
        raise HTTPException(
            status_code=400,
            detail=f"Bundle resource_id '{bundle.resource_id}' does not match path resource_id '{resource_id}'",
        )

    await ContractBundleStore.upsert_active_bundle(db, bundle)
    await db.commit()

    return BundleResponse(bundle=bundle)


@router.get(
    "/reports",
    response_model=ReportsListResponse,
    summary="List validation reports",
    description="List validation reports with optional filtering by scope and target.",
)
async def list_reports(
    scope: Optional[str] = Query(
        None,
        description="Filter by scope (resource, run, promotion, merge)",
    ),
    target_id: Optional[str] = Query(
        None,
        description="Filter by target ID",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of reports to return",
    ),
    db: AsyncSession = Depends(get_db),
) -> ReportsListResponse:
    """List validation reports with optional filtering."""
    reports = await ValidationReportStore.list_reports(
        db,
        scope=scope,
        target_id=target_id,
        limit=limit,
    )
    return ReportsListResponse(reports=reports)
