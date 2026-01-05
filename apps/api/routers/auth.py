"""Authentication router for API key management and session login.

Provides endpoints for:
- Creating API keys (POST /auth/keys)
- Listing API keys (GET /auth/keys)
- Getting key details (GET /auth/keys/{id})
- Revoking keys (DELETE /auth/keys/{id})
- Session login (POST /auth/login)
- Session logout (POST /auth/logout)
- User registration for dev (POST /auth/register)

All endpoints except login/register require authentication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from libs.core.auth import (
    AuthService,
    InvalidAPIKeyError,
    InvalidCredentialsError,
    InvalidSessionError,
)
from libs.core.rbac.models import ActorContext
from libs.core.settings import get_settings

router = APIRouter(prefix="/auth", tags=["Auth"])

SESSION_COOKIE_NAME = "optaic_session"


# =============================================================================
# Schemas
# =============================================================================


class APIKeyCreate(BaseModel):
    """Request to create a new API key."""

    name: str = Field(..., min_length=1, max_length=255, examples=["Production SDK"])
    description: Optional[str] = Field(
        None, max_length=1024, examples=["Key for production environment"]
    )
    scopes: Optional[list[str]] = Field(
        None, examples=[["read", "write"]], description="Permission scopes (optional)"
    )
    expires_in_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        examples=[90],
        description="Days until expiry (max 365, omit for no expiry)",
    )


class APIKeyCreated(BaseModel):
    """Response when API key is created.

    IMPORTANT: The `key` field contains the full API key and is
    returned ONCE. It cannot be retrieved again after this response.
    """

    id: UUID
    key: str = Field(
        ..., description="Full API key - SAVE THIS, it cannot be recovered"
    )
    key_prefix: str = Field(..., description="Public key prefix")
    name: str
    description: Optional[str] = None
    scopes: list[str] = []
    status: str
    expires_at: Optional[datetime] = None
    created_at: datetime


class APIKeyOut(BaseModel):
    """API key details (without secret)."""

    id: UUID
    key_prefix: str
    name: str
    description: Optional[str] = None
    scopes: list[str] = []
    status: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class APIKeyList(BaseModel):
    """List of API keys."""

    items: list[APIKeyOut]
    total: int


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/keys",
    response_model=APIKeyCreated,
    status_code=201,
    summary="Create API Key",
    description="Create a new API key for SDK authentication. "
    "The full key is returned ONCE in the response. Store it securely.",
)
async def create_api_key(
    payload: APIKeyCreate = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreated:
    """Create a new API key.

    The response contains the full API key which is shown ONCE.
    Store it securely - it cannot be retrieved again.
    """
    auth_service = AuthService()

    full_key, api_key = await auth_service.create_api_key(
        db,
        tenant_id=actor.tenant_id,
        principal_id=actor.id,
        name=payload.name,
        description=payload.description,
        scopes=payload.scopes,
        expires_in_days=payload.expires_in_days,
        created_by=actor.id,
    )

    await db.commit()

    return APIKeyCreated(
        id=api_key.id,
        key=full_key,  # Only returned once!
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        description=api_key.description,
        scopes=api_key.scopes,
        status=api_key.status,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


@router.get(
    "/keys",
    response_model=APIKeyList,
    summary="List API Keys",
    description="List all API keys for the current principal.",
)
async def list_api_keys(
    include_revoked: bool = Query(
        False, description="Include revoked keys in the list"
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> APIKeyList:
    """List API keys for the current principal."""
    auth_service = AuthService()

    keys = await auth_service.list_api_keys(
        db,
        tenant_id=actor.tenant_id,
        principal_id=actor.id,
        include_revoked=include_revoked,
    )

    items = [
        APIKeyOut(
            id=k.id,
            key_prefix=k.key_prefix,
            name=k.name,
            description=k.description,
            scopes=k.scopes,
            status=k.status,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            revoked_at=k.revoked_at,
        )
        for k in keys
    ]

    return APIKeyList(items=items, total=len(items))


@router.get(
    "/keys/{key_id}",
    response_model=APIKeyOut,
    summary="Get API Key Details",
    description="Get details for a specific API key.",
)
async def get_api_key(
    key_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> APIKeyOut:
    """Get details for a specific API key."""
    from libs.db.models.auth import APIKey

    api_key = await db.get(APIKey, key_id)

    if not api_key or api_key.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="API key not found")

    # Only allow viewing own keys or if admin (future enhancement)
    if api_key.principal_id != actor.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this key")

    return APIKeyOut(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        description=api_key.description,
        scopes=api_key.scopes,
        status=api_key.status,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
    )


@router.delete(
    "/keys/{key_id}",
    response_model=APIKeyOut,
    summary="Revoke API Key",
    description="Revoke an API key. This action cannot be undone.",
)
async def revoke_api_key(
    key_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> APIKeyOut:
    """Revoke an API key.

    Once revoked, the key can no longer be used for authentication.
    This action cannot be undone.
    """
    auth_service = AuthService()

    try:
        api_key = await auth_service.revoke_api_key(
            db,
            key_id=key_id,
            revoked_by=actor.id,
            tenant_id=actor.tenant_id,
        )
    except InvalidAPIKeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    await db.commit()

    return APIKeyOut(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        description=api_key.description,
        scopes=api_key.scopes,
        status=api_key.status,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked_at=api_key.revoked_at,
    )


# =============================================================================
# User Info Endpoint
# =============================================================================


class UserInfo(BaseModel):
    """Current user information."""

    principal_id: UUID
    tenant_id: UUID
    kind: str
    auth_method: str = Field(
        ..., description="Authentication method used (api_key, oauth, dev)"
    )


@router.get(
    "/me",
    response_model=UserInfo,
    summary="Get Current User",
    description="Get information about the currently authenticated user.",
)
async def get_current_user(
    actor: ActorContext = Depends(get_actor),
) -> UserInfo:
    """Get information about the currently authenticated user."""
    # Determine auth method from traits (future enhancement)
    # For now, default to unknown
    auth_method = actor.traits.get("auth_method", "unknown")

    return UserInfo(
        principal_id=actor.id,
        tenant_id=actor.tenant_id,
        kind=actor.kind,
        auth_method=auth_method,
    )


# =============================================================================
# Session Login/Logout (Dev Mode)
# =============================================================================


class LoginRequest(BaseModel):
    """Login request with username and password."""

    tenant_id: UUID = Field(..., description="Tenant ID to log into")
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=255)


class LoginResponse(BaseModel):
    """Login response with session info."""

    principal_id: UUID
    tenant_id: UUID
    expires_at: datetime
    message: str = "Login successful"


class RegisterRequest(BaseModel):
    """Register a new local credential (dev mode only)."""

    tenant_id: UUID = Field(..., description="Tenant ID")
    principal_id: UUID = Field(..., description="Principal ID to attach credential to")
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6, max_length=255)


class RegisterResponse(BaseModel):
    """Registration response."""

    id: UUID
    username: str
    principal_id: UUID
    message: str = "Registration successful"


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login with Username/Password",
    description="Authenticate with username and password. Returns a session cookie.",
)
async def login(
    response: Response,
    payload: LoginRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Login with username and password.

    Sets an httponly session cookie on successful authentication.
    """
    settings = get_settings()

    if not settings.dev_auth_enabled:
        raise HTTPException(
            status_code=403,
            detail="Local login is only available in development mode",
        )

    auth_service = AuthService()

    try:
        credential = await auth_service.validate_local_credential(
            db,
            tenant_id=payload.tenant_id,
            username=payload.username,
            password=payload.password,
        )
        await db.commit()
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    # Create session
    session = auth_service.create_session(
        principal_id=credential.principal_id,
        tenant_id=credential.tenant_id,
    )

    # Set session cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.session_id,
        httponly=True,
        secure=not settings.dev_auth_enabled,  # Secure in production
        samesite="lax",
        max_age=24 * 60 * 60,  # 24 hours
    )

    return LoginResponse(
        principal_id=session.principal_id,
        tenant_id=session.tenant_id,
        expires_at=session.expires_at,
    )


@router.post(
    "/logout",
    summary="Logout",
    description="End the current session and clear the session cookie.",
)
async def logout(
    response: Response,
    session_id: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> dict:
    """Logout and clear session."""
    if session_id:
        auth_service = AuthService()
        auth_service.destroy_session(session_id)

    # Clear session cookie
    response.delete_cookie(key=SESSION_COOKIE_NAME)

    return {"message": "Logged out successfully"}


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register Local Credential",
    description="Create a local username/password credential (dev mode only).",
)
async def register(
    payload: RegisterRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> RegisterResponse:
    """Register a new local credential.

    This is for development/testing only. In production, use OIDC.
    """
    settings = get_settings()

    if not settings.dev_auth_enabled:
        raise HTTPException(
            status_code=403,
            detail="Local registration is only available in development mode",
        )

    auth_service = AuthService()

    try:
        credential = await auth_service.create_local_credential(
            db,
            tenant_id=payload.tenant_id,
            principal_id=payload.principal_id,
            username=payload.username,
            password=payload.password,
        )
        await db.commit()
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return RegisterResponse(
        id=credential.id,
        username=credential.username,
        principal_id=credential.principal_id,
    )


@router.get(
    "/session",
    response_model=UserInfo,
    summary="Get Session Info",
    description="Get information about the current session.",
)
async def get_session_info(
    session_id: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
    db: AsyncSession = Depends(get_db),
) -> UserInfo:
    """Get current session info from cookie."""
    if not session_id:
        raise HTTPException(status_code=401, detail="No session cookie")

    auth_service = AuthService()

    try:
        session = auth_service.validate_session(session_id)
    except InvalidSessionError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    # Get principal kind from database
    from libs.db.models.identity import Principal

    principal = await db.get(Principal, session.principal_id)
    kind = principal.kind if principal else "user"

    return UserInfo(
        principal_id=session.principal_id,
        tenant_id=session.tenant_id,
        kind=kind,
        auth_method="session",
    )
