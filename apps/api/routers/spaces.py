"""Spaces Router - Space and User Management.

Provides endpoints for:
- POST /users - Create user with Personal Space (admin only)
- POST /spaces/team - Create Team Space (admin only)
- POST /spaces/{space_id}/subspaces - Create custom subspace
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.rbac_utils import authorize_or_403
from apps.api.schemas import (
    CustomSubspaceCreate,
    SpaceOut,
    SubspaceOut,
    TeamSpaceCreate,
    UserCreate,
    UserWithSpaceOut,
)
from apps.api.services.space_service import SpaceService
from libs.core.bootstrap import SYSTEM_SPACE_ID
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.resource import Resource

router = APIRouter(tags=["Spaces"])


async def _get_tenant_root(db: AsyncSession, tenant_id: UUID) -> Resource:
    """Get the TenantRoot resource for a tenant."""
    result = await db.scalars(
        select(Resource)
        .where(
            Resource.tenant_id == tenant_id,
            Resource.type == "TenantRoot",
        )
        .order_by(Resource.created_at)
    )
    root = result.first()
    if not root:
        raise HTTPException(status_code=404, detail="Tenant root resource not found")
    return root


@router.post("/users", response_model=UserWithSpaceOut, status_code=201)
async def create_user_with_space(
    payload: UserCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create user with Personal Space",
                "value": {
                    "display_name": "Alice Smith",
                    "email": "alice@example.com",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> UserWithSpaceOut:
    """Create a new user with a Personal Space.

    Creates:
    1. Principal (user account)
    2. Personal Space
    3. Official + Staging sub-spaces
    4. Grants owner role on Personal Space
    5. Grants viewer role on System Space

    Requires INVITE_CREATE permission on TenantRoot.
    """
    root = await _get_tenant_root(db, actor.tenant_id)
    await authorize_or_403(db, actor, Permission.INVITE_CREATE, root.id)
    # Note: NOT calling reset_session to avoid expiring objects in session

    service = SpaceService()

    # Create user with Personal Space
    result = await service.create_user_with_personal_space(
        db,
        actor,
        display_name=payload.display_name,
        email=payload.email,
        tenant_root_id=root.id,
    )

    # Grant VIEW access to System Space
    await service.grant_system_space_view_access(
        db,
        actor,
        principal_id=result.principal_id,
        system_space_id=SYSTEM_SPACE_ID,
    )

    await db.commit()

    return UserWithSpaceOut(
        principal_id=result.principal_id,
        display_name=payload.display_name,
        email=payload.email,
        space_id=result.personal_space.space_id,
        official_subspace_id=result.personal_space.official_subspace_id,
        staging_subspace_id=result.personal_space.staging_subspace_id,
    )


@router.post("/spaces/team", response_model=SpaceOut, status_code=201)
async def create_team_space(
    payload: TeamSpaceCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create Team Space",
                "value": {
                    "name": "Quant Research Team",
                    "owner_principal_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1",
                    "description": "Our research team space",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SpaceOut:
    """Create a Team Space with an assigned owner.

    Creates:
    1. Team Space
    2. Official + Staging sub-spaces
    3. Grants owner role to owner_principal_id
    4. Optionally grants operator role to members

    Requires INVITE_CREATE permission on TenantRoot.
    """
    root = await _get_tenant_root(db, actor.tenant_id)
    await authorize_or_403(db, actor, Permission.INVITE_CREATE, root.id)
    # Note: NOT calling reset_session to avoid expiring objects in session

    service = SpaceService()

    result = await service.create_team_space(
        db,
        actor,
        name=payload.name,
        owner_principal_id=payload.owner_principal_id,
        tenant_root_id=root.id,
        member_principal_ids=payload.member_principal_ids,
        description=payload.description,
    )

    await db.commit()

    return SpaceOut(
        space_id=result.space_id,
        name=payload.name,
        space_kind="team",
        official_subspace_id=result.official_subspace_id,
        staging_subspace_id=result.staging_subspace_id,
    )


@router.post(
    "/spaces/{space_id}/subspaces", response_model=SubspaceOut, status_code=201
)
async def create_custom_subspace(
    space_id: UUID,
    payload: CustomSubspaceCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create custom subspace",
                "value": {
                    "name": "Experiments",
                    "description": "Custom subspace for experiments",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SubspaceOut:
    """Create a custom subspace under a space.

    Users can create additional subspaces beyond Official and Staging.

    Requires RESOURCE_CREATE_CHILD permission on the Space.
    """
    # Verify the space exists
    space = await db.get(Resource, space_id)
    if not space or space.type != "Space":
        raise HTTPException(status_code=404, detail="Space not found")

    if space.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot access this space")

    await authorize_or_403(db, actor, Permission.RESOURCE_CREATE_CHILD, space_id)
    # Note: NOT calling reset_session to avoid expiring objects in session

    service = SpaceService()

    result = await service.create_custom_subspace(
        db,
        actor,
        name=payload.name,
        parent_space_id=space_id,
        description=payload.description,
    )

    await db.commit()

    return SubspaceOut(
        id=UUID(result["id"]),
        name=result["name"],
        subspace_kind=result["subspace_kind"],
        parent_space_id=UUID(result["parent_space_id"]),
    )
