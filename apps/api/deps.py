from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator, Annotated, Optional
from uuid import UUID

import structlog
from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.rbac.models import ActorContext
from libs.core.settings import get_settings
from apps.api.agent_utils import AgentMeta
from libs.db.models.identity import Principal
from libs.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

SESSION_COOKIE_NAME = "optaic_session"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# =============================================================================
# Multi-Auth Flow: API Key > OAuth > Dev Headers
# =============================================================================


async def get_authenticated_principal(
    authorization: Annotated[Optional[str], Header(alias="Authorization")] = None,
    x_api_key: Annotated[Optional[str], Header(alias="X-API-Key")] = None,
    x_principal_id: Annotated[Optional[str], Header(alias="X-Principal-Id")] = None,
    x_tenant_id: Annotated[Optional[str], Header(alias="X-Tenant-Id")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
    db: AsyncSession = Depends(get_db),
) -> tuple[UUID, UUID, str]:
    """Authenticate via API key, OAuth token, session cookie, or dev headers.

    Authentication priority:
    1. X-API-Key header (SDK clients)
    2. Authorization: Bearer (OAuth JWT)
    3. Session cookie (web GUI login)
    4. X-Principal-Id + X-Tenant-Id (dev mode only)

    Returns:
        Tuple of (principal_id, tenant_id, auth_method)

    Raises:
        HTTPException: 401 if authentication fails
    """
    settings = get_settings()

    # Priority 1: API Key authentication
    if x_api_key:
        from libs.core.auth import AuthService, InvalidAPIKeyError

        auth_service = AuthService()
        try:
            api_key = await auth_service.validate_api_key(db, x_api_key)
            logger.debug(
                "auth.api_key_authenticated",
                key_prefix=api_key.key_prefix,
                principal_id=str(api_key.principal_id),
            )
            return api_key.principal_id, api_key.tenant_id, "api_key"
        except InvalidAPIKeyError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    # Priority 2: OAuth Bearer token
    if authorization and authorization.lower().startswith("bearer "):
        if not settings.oidc_enabled:
            raise HTTPException(
                status_code=401,
                detail="OAuth authentication not enabled",
            )

        from libs.core.auth import AuthService, InvalidOIDCTokenError

        token = authorization[7:]  # Remove "Bearer " prefix
        auth_service = AuthService()

        try:
            # Validate token
            claims = await auth_service.validate_oidc_token(db, token)

            # For OIDC, we need tenant_id from headers or claims
            tenant_id = None
            if x_tenant_id:
                try:
                    tenant_id = UUID(x_tenant_id)
                except ValueError:
                    raise HTTPException(
                        status_code=400, detail="Invalid X-Tenant-Id header"
                    )
            elif "tenant_id" in claims:
                tenant_id = UUID(claims["tenant_id"])
            else:
                raise HTTPException(
                    status_code=400,
                    detail="X-Tenant-Id header required for OAuth authentication",
                )

            # Get or create principal
            principal = await auth_service.get_or_create_principal_from_oidc(
                db, claims, tenant_id
            )
            await db.commit()

            logger.debug(
                "auth.oidc_authenticated",
                sub=claims.get("sub"),
                principal_id=str(principal.id),
            )
            return principal.id, tenant_id, "oauth"

        except InvalidOIDCTokenError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    # Priority 3: Session cookie authentication (web GUI)
    if session_cookie:
        from libs.core.auth import AuthService, InvalidSessionError

        auth_service = AuthService()
        try:
            session = auth_service.validate_session(session_cookie)
            logger.debug(
                "auth.session_authenticated",
                session_id=session_cookie[:8] + "...",
                principal_id=str(session.principal_id),
            )
            return session.principal_id, session.tenant_id, "session"
        except InvalidSessionError:
            # Session invalid/expired - fall through to other methods
            pass

    # Priority 4: Dev mode header-based authentication
    if settings.dev_auth_enabled:
        if x_principal_id and x_tenant_id:
            try:
                principal_id = UUID(x_principal_id)
                tenant_id = UUID(x_tenant_id)

                logger.debug(
                    "auth.dev_mode_authenticated",
                    principal_id=str(principal_id),
                    tenant_id=str(tenant_id),
                )
                return principal_id, tenant_id, "dev"
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid X-Principal-Id or X-Tenant-Id header",
                ) from exc

    # No valid authentication method found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide X-API-Key, Authorization: Bearer, "
        "session cookie, or (dev mode) X-Principal-Id and X-Tenant-Id headers.",
    )


async def get_actor(
    auth: tuple[UUID, UUID, str] = Depends(get_authenticated_principal),
    db: AsyncSession = Depends(get_db),
) -> ActorContext:
    """Get actor context from authenticated principal.

    Uses the multi-auth flow to get principal_id, tenant_id, and auth_method,
    then validates the principal exists in the database.
    """
    principal_id, tenant_id, auth_method = auth

    result = await db.scalars(select(Principal).where(Principal.id == principal_id))
    principal = result.first()
    if not principal:
        raise HTTPException(status_code=401, detail="Unknown principal")
    if principal.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403, detail="Principal does not belong to tenant"
        )
    return ActorContext(
        id=principal.id,
        tenant_id=tenant_id,
        kind=principal.kind,
        traits={"auth_method": auth_method},
    )


# =============================================================================
# Legacy Dependencies (for backwards compatibility)
# =============================================================================


async def get_principal_id(
    x_principal_id: Annotated[str, Header(alias="X-Principal-Id")],
) -> UUID:
    """Legacy: Get principal ID from header.

    DEPRECATED: Use get_authenticated_principal instead.
    """
    try:
        return UUID(x_principal_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid X-Principal-Id header"
        ) from exc


async def get_tenant_id(
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-Id")],
) -> UUID:
    """Legacy: Get tenant ID from header.

    DEPRECATED: Use get_authenticated_principal instead.
    """
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid X-Tenant-Id header"
        ) from exc


async def get_agent_meta(
    x_agent_source_activity_id: Annotated[
        Optional[str], Header(alias="X-Agent-Source-Activity-Id")
    ] = None,
    x_agent_model: Annotated[Optional[str], Header(alias="X-Agent-Model")] = None,
    x_agent_prompt_hash: Annotated[
        Optional[str], Header(alias="X-Agent-Prompt-Hash")
    ] = None,
    x_agent_tool_name: Annotated[
        Optional[str], Header(alias="X-Agent-Tool-Name")
    ] = None,
    x_agent_tool_args_hash: Annotated[
        Optional[str], Header(alias="X-Agent-Tool-Args-Hash")
    ] = None,
    x_agent_tool_result_hash: Annotated[
        Optional[str], Header(alias="X-Agent-Tool-Result-Hash")
    ] = None,
) -> AgentMeta:
    source_id = None
    if x_agent_source_activity_id:
        try:
            source_id = UUID(x_agent_source_activity_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid X-Agent-Source-Activity-Id header"
            ) from exc
    return AgentMeta(
        source_activity_id=source_id,
        model=x_agent_model,
        prompt_hash=x_agent_prompt_hash,
        tool_name=x_agent_tool_name,
        tool_args_hash=x_agent_tool_args_hash,
        tool_result_hash=x_agent_tool_result_hash,
    )


async def reset_session(db: AsyncSession) -> None:
    if db.in_transaction():
        await db.rollback()


def get_guardrails_engine() -> "GuardrailsEngine":  # noqa: F821
    from optaic.guardrails.runtime.engine import GuardrailsEngine

    return GuardrailsEngine()


def get_orchestrator() -> "OrchestratorAdapter":  # noqa: F821
    """Get the orchestrator adapter.

    Returns LocalOrchestrator by default. In production with Prefect,
    this would return PrefectOrchestrator configured via settings.
    """
    from libs.orchestration import LocalOrchestrator

    return LocalOrchestrator()


async def get_status_store(
    db: AsyncSession = Depends(get_db),
) -> "StatusStore":  # noqa: F821
    """Get the StatusStore instance."""
    from libs.orchestration import StatusStore

    return StatusStore(db)
