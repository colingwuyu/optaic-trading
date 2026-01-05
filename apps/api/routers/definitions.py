"""Definitions Upload API Router.

Provides endpoints for:
- Uploading definition plugins (ZIP files)
- Deploying draft definitions
- Re-running tests
- Listing and viewing definitions
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    DefinitionDeployOut,
    DefinitionDetailsOut,
    DefinitionListItem,
    DefinitionListOut,
    DefinitionTestRerunOut,
    DefinitionUploadOut,
)
from apps.api.services.definition_upload_service import (
    DefinitionUploadError,
    get_definition_upload_service,
)
from apps.api.services.extension_loader import (
    ManifestValidationError,
    ZipValidationError,
)
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.definition_upload import DefinitionUpload
from libs.db.models.quant import (
    AccessorDefinition,
    OpDefinition,
    PipelineDefinition,
    StoreDefinition,
)
from libs.db.models.resource import Resource

router = APIRouter(prefix="/definitions", tags=["Definitions"])


# Maximum upload size (50 MB)
MAX_UPLOAD_SIZE = 50 * 1024 * 1024


# --- Upload Endpoints ---


@router.post("/upload", response_model=DefinitionUploadOut, status_code=201)
async def upload_definition(
    file: UploadFile = File(..., description="ZIP file containing definition plugin"),
    target_parent_id: Optional[UUID] = Form(
        None, description="Parent resource ID (Project or Space)"
    ),
    skip_tests: bool = Form(False, description="Skip test execution"),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DefinitionUploadOut:
    """Upload a definition plugin from a ZIP file.

    The ZIP must contain a manifest.json with required fields:
    - name: Definition name
    - version: Semantic version
    - definition_type: PipelineDef, StoreDef, AccessorDef, OpDef, etc.
    - module_file: Python file containing the class
    - class_name: Class to register in factory
    - interface_spec: Interface the class implements

    Optional fields:
    - test_suite_file: pytest file for tests
    - category: Definition category
    - description: Human-readable description
    - input_schema, output_schema, parameters_schema: JSON schemas
    - guardrail_contracts: Validation contracts
    - dependencies: Required packages

    If test_suite_file is specified, tests are run automatically.
    Status is 'active' if tests pass/skipped, 'draft' if tests fail.

    Args:
        file: ZIP file upload
        target_parent_id: Parent resource (defaults to actor's default space)
        skip_tests: Skip test execution
        actor: Actor context
        db: Database session

    Returns:
        Upload result with resource info
    """
    # Validate file
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP archive")

    # Read content with size limit
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_SIZE // 1024 // 1024}MB)",
        )

    # If target_parent_id specified, check permission
    if target_parent_id:
        parent = await get_resource_or_404(db, actor.tenant_id, target_parent_id)
        await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, parent.id)

    # Process upload
    service = get_definition_upload_service()
    try:
        result = await service.upload(
            session=db,
            actor=actor,
            zip_content=content,
            original_filename=file.filename,
            target_parent_id=target_parent_id,
            skip_tests=skip_tests,
        )
    except ZipValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid ZIP: {e}")
    except ManifestValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={"message": str(e), "issues": e.issues},
        )
    except DefinitionUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DefinitionUploadOut(
        id=UUID(result["id"]),
        name=result["name"],
        version=result["version"],
        definition_type=result["definition_type"],
        code_ref=result["code_ref"],
        status=result["status"],
        evaluation_status=result["evaluation_status"],
        artifact_ref=result["artifact_ref"],
        tests_total=result.get("tests_total"),
        tests_passed=result.get("tests_passed"),
        tests_failed=result.get("tests_failed"),
        issues=result.get("issues", []),
    )


@router.post("/{definition_id}/deploy", response_model=DefinitionDeployOut)
async def deploy_definition(
    definition_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DefinitionDeployOut:
    """Deploy a draft definition.

    Changes status from draft to active and registers plugin in factory.
    Only draft definitions can be deployed.

    Args:
        definition_id: Definition resource ID
        actor: Actor context
        db: Database session

    Returns:
        Deployment result
    """
    # Get resource and check permission
    resource = await get_resource_or_404(db, actor.tenant_id, definition_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = get_definition_upload_service()
    try:
        result = await service.deploy(
            session=db,
            actor=actor,
            definition_id=definition_id,
        )
    except DefinitionUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DefinitionDeployOut(
        id=UUID(result["id"]),
        name=result["name"],
        code_ref=result["code_ref"],
        status=result["status"],
    )


@router.post("/{definition_id}/rerun-tests", response_model=DefinitionTestRerunOut)
async def rerun_tests(
    definition_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DefinitionTestRerunOut:
    """Re-run tests for a definition.

    Runs the test suite again and updates evaluation status.
    If tests pass and status is draft, automatically deploys.

    Args:
        definition_id: Definition resource ID
        actor: Actor context
        db: Database session

    Returns:
        Test results
    """
    # Get resource and check permission
    resource = await get_resource_or_404(db, actor.tenant_id, definition_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_UPDATE, resource.id)

    service = get_definition_upload_service()
    try:
        result = await service.rerun_tests(
            session=db,
            actor=actor,
            definition_id=definition_id,
        )
    except DefinitionUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DefinitionTestRerunOut(
        id=UUID(result["id"]),
        evaluation_status=result["evaluation_status"],
        tests_total=result["tests_total"],
        tests_passed=result["tests_passed"],
        tests_failed=result["tests_failed"],
        duration_ms=result["duration_ms"],
        passed=result["passed"],
        failures=result.get("failures", []),
    )


@router.get("/{definition_id}", response_model=DefinitionDetailsOut)
async def get_definition_details(
    definition_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DefinitionDetailsOut:
    """Get detailed information about a definition upload.

    Includes manifest, test results, and file info.

    Args:
        definition_id: Definition resource ID
        actor: Actor context
        db: Database session

    Returns:
        Definition details
    """
    # Get resource and check permission
    resource = await get_resource_or_404(db, actor.tenant_id, definition_id)
    await authorize_or_403(db, actor, Permission.RESOURCE_READ, resource.id)

    service = get_definition_upload_service()
    result = await service.get_upload_details(
        session=db,
        actor=actor,
        definition_id=definition_id,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Upload details not found")

    return DefinitionDetailsOut(**result)


@router.get("", response_model=DefinitionListOut)
async def list_definitions(
    definition_type: Optional[str] = Query(
        None, description="Filter by type (PipelineDef, StoreDef, etc.)"
    ),
    status: Optional[str] = Query(None, description="Filter by status (draft, active)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    parent_id: Optional[UUID] = Query(None, description="Filter by parent resource"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> DefinitionListOut:
    """List definition resources.

    Returns all Definition resources the actor can read.
    Supports filtering by type, status, category, and parent.

    Args:
        definition_type: Filter by definition type
        status: Filter by status
        category: Filter by category
        parent_id: Filter by parent resource
        limit: Maximum results
        cursor: Pagination cursor
        actor: Actor context
        db: Database session

    Returns:
        List of definitions
    """
    # Build query for definition types
    definition_types = [
        "PipelineDef",
        "StoreDef",
        "AccessorDef",
        "OpDef",
        "MLModuleDef",
        "PortfolioOptimizerDef",
    ]

    if definition_type:
        if definition_type not in definition_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid definition_type. Must be one of: {', '.join(definition_types)}",
            )
        definition_types = [definition_type]

    # Query resources
    stmt = select(Resource).where(
        Resource.tenant_id == actor.tenant_id,
        Resource.type.in_(definition_types),
    )

    if status:
        stmt = stmt.where(Resource.status == status)

    if parent_id:
        stmt = stmt.where(Resource.parent_id == parent_id)

    # Handle cursor pagination
    if cursor:
        try:
            cursor_id = UUID(cursor)
            stmt = stmt.where(Resource.id > cursor_id)
        except ValueError:
            pass

    stmt = stmt.order_by(Resource.id).limit(
        limit + 1
    )  # Fetch one extra for next_cursor

    result = await db.scalars(stmt)
    resources = list(result.all())

    # Check for next page
    next_cursor = None
    if len(resources) > limit:
        resources = resources[:limit]
        next_cursor = str(resources[-1].id)

    # Get extension data for category and code_ref
    items = []
    for resource in resources:
        # Try to get code_ref and category from extension table
        code_ref = None
        category_value = None

        if resource.type == "PipelineDef":
            ext = await db.get(PipelineDefinition, resource.id)
            if ext:
                code_ref = ext.code_ref
                category_value = ext.category
        elif resource.type == "StoreDef":
            ext = await db.get(StoreDefinition, resource.id)
            if ext:
                code_ref = ext.code_ref
                category_value = ext.backend_type
        elif resource.type == "AccessorDef":
            ext = await db.get(AccessorDefinition, resource.id)
            if ext:
                code_ref = ext.code_ref
                category_value = ext.accessor_type
        elif resource.type == "OpDef":
            ext = await db.get(OpDefinition, resource.id)
            if ext:
                code_ref = ext.code_ref
                category_value = ext.category

        # Apply category filter if specified
        if category and category_value != category:
            continue

        # Get version from upload record if available
        version = None
        upload_stmt = select(DefinitionUpload).where(
            DefinitionUpload.resource_id == resource.id
        )
        upload_result = await db.scalars(upload_stmt)
        upload = upload_result.first()
        if upload:
            version = upload.manifest_version

        items.append(
            DefinitionListItem(
                id=resource.id,
                name=resource.name,
                definition_type=resource.type,
                code_ref=code_ref,
                status=resource.status,
                category=category_value,
                version=version,
            )
        )

    return DefinitionListOut(items=items, next_cursor=next_cursor)
