"""Authentication service for API keys, OIDC, and session-based auth.

Provides:
- API key creation, validation, and revocation
- OIDC token validation against Keycloak/Azure AD or other providers
- Principal mapping from OIDC subjects
- Local credential (username/password) for dev GUI
- Session-based authentication for web GUI

API Key Format:
- Full key: optaic_abc123def456.ghijklmnopqrstuvwxyz0123456789ABCD
- Prefix (public): optaic_abc123def456
- Secret (hashed): .ghijklmnopqrstuvwxyz0123456789ABCD
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.core.settings import get_settings
from libs.db.models.auth import (
    APIKey,
    LocalCredential,
    OIDCPrincipalMapping,
    OIDCProvider,
)
from libs.db.models.identity import Principal

logger = structlog.get_logger(__name__)


# =============================================================================
# Session Store (In-Memory for Dev)
# =============================================================================


@dataclass
class Session:
    """Session data for authenticated user."""

    session_id: str
    principal_id: UUID
    tenant_id: UUID
    created_at: datetime
    expires_at: datetime


# Simple in-memory session store - replace with Redis/DB for production
_session_store: dict[str, Session] = {}

SESSION_DURATION_HOURS = 24  # Sessions expire after 24 hours

# Use argon2 if available, fall back to sha256 for simplicity
# In production, always use argon2id
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _hasher = PasswordHasher()
    _USE_ARGON2 = True
except ImportError:
    _USE_ARGON2 = False
    logger.warning(
        "auth.argon2_not_available",
        message="argon2-cffi not installed, using SHA256 (NOT RECOMMENDED for production)",
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_key(key: str) -> str:
    """Hash an API key using argon2id or SHA256 fallback."""
    if _USE_ARGON2:
        return _hasher.hash(key)
    # Fallback for development/testing
    return hashlib.sha256(key.encode()).hexdigest()


def _verify_key(key: str, key_hash: str) -> bool:
    """Verify an API key against its hash."""
    if _USE_ARGON2:
        try:
            _hasher.verify(key_hash, key)
            return True
        except VerifyMismatchError:
            return False
    # Fallback for SHA256
    return hashlib.sha256(key.encode()).hexdigest() == key_hash


def _generate_key_parts(prefix: str) -> tuple[str, str, str]:
    """Generate API key parts.

    Returns:
        Tuple of (full_key, key_prefix, key_hash)
    """
    # Generate random parts
    public_id = secrets.token_hex(6)  # 12 chars
    secret = secrets.token_urlsafe(24)  # ~32 chars

    # Build key
    key_prefix = f"{prefix}{public_id}"
    full_key = f"{key_prefix}.{secret}"
    key_hash = _hash_key(full_key)

    return full_key, key_prefix, key_hash


class AuthError(Exception):
    """Base exception for authentication errors."""

    pass


class InvalidAPIKeyError(AuthError):
    """Raised when an API key is invalid or expired."""

    pass


class InvalidOIDCTokenError(AuthError):
    """Raised when an OIDC token is invalid."""

    pass


class InvalidCredentialsError(AuthError):
    """Raised when username/password is invalid."""

    pass


class InvalidSessionError(AuthError):
    """Raised when session is invalid or expired."""

    pass


class AuthService:
    """Service for authentication operations.

    Handles:
    - API key lifecycle (create, validate, revoke, list)
    - OIDC token validation
    - Principal mapping from OIDC claims
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    # =========================================================================
    # API Key Operations
    # =========================================================================

    async def create_api_key(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        principal_id: UUID,
        name: str,
        description: str | None = None,
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
        created_by: UUID | None = None,
    ) -> tuple[str, APIKey]:
        """Create a new API key.

        Args:
            session: Database session
            tenant_id: Tenant the key belongs to
            principal_id: Principal the key authenticates as
            name: Human-readable name for the key
            description: Optional description
            scopes: Optional permission scopes
            expires_in_days: Optional expiry in days from now
            created_by: Principal who created this key

        Returns:
            Tuple of (full_key, APIKey record)
            IMPORTANT: The full_key is returned ONCE and cannot be recovered.
        """
        # Generate key parts
        full_key, key_prefix, key_hash = _generate_key_parts(
            self._settings.api_key_prefix
        )

        # Calculate expiry
        expires_at = None
        if expires_in_days:
            expires_at = utcnow() + timedelta(days=expires_in_days)

        # Create record
        api_key = APIKey(
            id=uuid4(),
            tenant_id=tenant_id,
            principal_id=principal_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            name=name,
            description=description,
            scopes=scopes or [],
            status="active",
            expires_at=expires_at,
            created_by=created_by or principal_id,
        )
        session.add(api_key)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=tenant_id,
            actor_principal_id=created_by or principal_id,
            resource_id=api_key.id,
            resource_type="APIKey",
            action="api_key.created",
            payload={
                "key_prefix": key_prefix,
                "name": name,
                "principal_id": str(principal_id),
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "auth.api_key_created",
            key_prefix=key_prefix,
            principal_id=str(principal_id),
            tenant_id=str(tenant_id),
        )

        return full_key, api_key

    async def validate_api_key(
        self,
        session: AsyncSession,
        key: str,
    ) -> APIKey:
        """Validate an API key and return its record.

        Args:
            session: Database session
            key: Full API key (prefix.secret)

        Returns:
            APIKey record if valid

        Raises:
            InvalidAPIKeyError: If key is invalid, expired, or revoked
        """
        # Extract prefix (everything before the last dot)
        if "." not in key:
            raise InvalidAPIKeyError("Invalid key format")

        key_prefix = key.rsplit(".", 1)[0]

        # Look up key by prefix
        result = await session.execute(
            select(APIKey).where(APIKey.key_prefix == key_prefix)
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            logger.warning(
                "auth.api_key_not_found",
                key_prefix=key_prefix,
            )
            raise InvalidAPIKeyError("API key not found")

        # Verify hash
        if not _verify_key(key, api_key.key_hash):
            logger.warning(
                "auth.api_key_invalid_secret",
                key_prefix=key_prefix,
            )
            raise InvalidAPIKeyError("Invalid API key")

        # Check status
        if api_key.status != "active":
            logger.warning(
                "auth.api_key_not_active",
                key_prefix=key_prefix,
                status=api_key.status,
            )
            raise InvalidAPIKeyError(f"API key is {api_key.status}")

        # Check expiry
        if api_key.expires_at:
            expires_at = api_key.expires_at
            # Handle naive datetime from SQLite
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < utcnow():
                # Update status to expired
                api_key.status = "expired"
                logger.warning(
                    "auth.api_key_expired",
                    key_prefix=key_prefix,
                )
                raise InvalidAPIKeyError("API key has expired")

        # Update last used
        api_key.last_used_at = utcnow()

        logger.debug(
            "auth.api_key_validated",
            key_prefix=key_prefix,
            principal_id=str(api_key.principal_id),
        )

        return api_key

    async def revoke_api_key(
        self,
        session: AsyncSession,
        *,
        key_id: UUID,
        revoked_by: UUID,
        tenant_id: UUID,
    ) -> APIKey:
        """Revoke an API key.

        Args:
            session: Database session
            key_id: API key ID to revoke
            revoked_by: Principal revoking the key
            tenant_id: Tenant ID (for validation)

        Returns:
            Updated APIKey record
        """
        api_key = await session.get(APIKey, key_id)
        if not api_key or api_key.tenant_id != tenant_id:
            raise InvalidAPIKeyError("API key not found")

        if api_key.status == "revoked":
            raise InvalidAPIKeyError("API key already revoked")

        api_key.status = "revoked"
        api_key.revoked_at = utcnow()
        api_key.revoked_by = revoked_by

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=tenant_id,
            actor_principal_id=revoked_by,
            resource_id=key_id,
            resource_type="APIKey",
            action="api_key.revoked",
            payload={
                "key_prefix": api_key.key_prefix,
                "name": api_key.name,
            },
        )
        await record_activity_with_outbox(session, envelope)

        logger.info(
            "auth.api_key_revoked",
            key_prefix=api_key.key_prefix,
            revoked_by=str(revoked_by),
        )

        return api_key

    async def list_api_keys(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        principal_id: UUID | None = None,
        include_revoked: bool = False,
    ) -> list[APIKey]:
        """List API keys for a tenant/principal.

        Args:
            session: Database session
            tenant_id: Tenant to list keys for
            principal_id: Optional principal filter
            include_revoked: Include revoked keys

        Returns:
            List of APIKey records (without secrets)
        """
        query = select(APIKey).where(APIKey.tenant_id == tenant_id)

        if principal_id:
            query = query.where(APIKey.principal_id == principal_id)

        if not include_revoked:
            query = query.where(APIKey.status != "revoked")

        query = query.order_by(APIKey.created_at.desc())

        result = await session.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # OIDC Operations
    # =========================================================================

    async def validate_oidc_token(
        self,
        session: AsyncSession,
        token: str,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Validate an OIDC/JWT token.

        Args:
            session: Database session
            token: JWT bearer token
            tenant_id: Optional tenant to validate against

        Returns:
            Token claims if valid

        Raises:
            InvalidOIDCTokenError: If token is invalid
        """
        # Lazy import jwt to avoid dependency if not using OIDC
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError as e:
            raise InvalidOIDCTokenError(
                "PyJWT not installed. Install with: pip install PyJWT"
            ) from e

        if not self._settings.oidc_enabled:
            raise InvalidOIDCTokenError("OIDC authentication is not enabled")

        issuer_url = self._settings.oidc_issuer_url
        if not issuer_url:
            raise InvalidOIDCTokenError("OIDC issuer URL not configured")

        # Get JWKS from issuer
        jwks_url = f"{issuer_url.rstrip('/')}/protocol/openid-connect/certs"

        try:
            jwks_client = PyJWKClient(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            # Decode and validate token
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=issuer_url,
                audience=self._settings.oidc_audience or None,
                options={
                    "verify_aud": bool(self._settings.oidc_audience),
                },
            )

            logger.debug(
                "auth.oidc_token_validated",
                sub=claims.get("sub"),
                iss=claims.get("iss"),
            )

            return claims

        except jwt.ExpiredSignatureError:
            raise InvalidOIDCTokenError("Token has expired")
        except jwt.InvalidIssuerError:
            raise InvalidOIDCTokenError("Invalid token issuer")
        except jwt.InvalidAudienceError:
            raise InvalidOIDCTokenError("Invalid token audience")
        except jwt.PyJWTError as e:
            logger.warning(
                "auth.oidc_token_invalid",
                error=str(e),
            )
            raise InvalidOIDCTokenError(f"Invalid token: {e}")

    async def get_or_create_principal_from_oidc(
        self,
        session: AsyncSession,
        claims: dict[str, Any],
        tenant_id: UUID,
    ) -> Principal:
        """Get or create a principal from OIDC claims.

        Args:
            session: Database session
            claims: OIDC token claims
            tenant_id: Tenant to create principal in

        Returns:
            Principal record
        """
        subject = claims.get("sub")
        if not subject:
            raise InvalidOIDCTokenError("Token missing 'sub' claim")

        # Find existing mapping
        result = await session.execute(
            select(OIDCPrincipalMapping)
            .join(OIDCProvider)
            .where(
                OIDCProvider.tenant_id == tenant_id,
                OIDCProvider.issuer_url == claims.get("iss"),
                OIDCPrincipalMapping.subject == subject,
            )
        )
        mapping = result.scalar_one_or_none()

        if mapping:
            # Update cached claims and last login
            mapping.email = claims.get("email")
            mapping.name = claims.get("name") or claims.get("preferred_username")
            mapping.claims_json = claims
            mapping.last_login_at = utcnow()

            # Return existing principal
            principal = await session.get(Principal, mapping.principal_id)
            if principal:
                return principal

        # No mapping found - check if we should auto-create
        provider_result = await session.execute(
            select(OIDCProvider).where(
                OIDCProvider.tenant_id == tenant_id,
                OIDCProvider.issuer_url == claims.get("iss"),
                OIDCProvider.enabled == True,  # noqa: E712
            )
        )
        provider = provider_result.scalar_one_or_none()

        if not provider:
            raise InvalidOIDCTokenError("No OIDC provider configured for this issuer")

        if not provider.auto_create_principals:
            raise InvalidOIDCTokenError(
                "Auto-creation disabled. Please contact administrator."
            )

        # Create new principal
        display_name = (
            claims.get("name")
            or claims.get("preferred_username")
            or claims.get("email")
            or f"oidc-{subject[:8]}"
        )
        email = claims.get("email")

        principal = Principal(
            id=uuid4(),
            tenant_id=tenant_id,
            kind="user",
            status="active",
            display_name=display_name,
            email=email,
        )
        session.add(principal)

        # Create mapping
        new_mapping = OIDCPrincipalMapping(
            id=uuid4(),
            provider_id=provider.id,
            principal_id=principal.id,
            subject=subject,
            email=email,
            name=display_name,
            claims_json=claims,
            last_login_at=utcnow(),
        )
        session.add(new_mapping)

        logger.info(
            "auth.oidc_principal_created",
            principal_id=str(principal.id),
            subject=subject,
            tenant_id=str(tenant_id),
        )

        return principal

    # =========================================================================
    # Local Credential Operations (Dev/Testing)
    # =========================================================================

    async def create_local_credential(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        principal_id: UUID,
        username: str,
        password: str,
    ) -> LocalCredential:
        """Create a local credential for dev/testing.

        Args:
            session: Database session
            tenant_id: Tenant ID
            principal_id: Principal to attach credential to (auto-created if doesn't exist)
            username: Username (unique within tenant)
            password: Plain text password (will be hashed)

        Returns:
            LocalCredential record
        """
        from libs.db.models.identity import Principal

        # Check if username already exists in tenant
        result = await session.execute(
            select(LocalCredential).where(
                LocalCredential.tenant_id == tenant_id,
                LocalCredential.username == username,
            )
        )
        if result.scalar_one_or_none():
            raise InvalidCredentialsError(f"Username '{username}' already exists")

        # Check if principal already has credential
        result = await session.execute(
            select(LocalCredential).where(
                LocalCredential.principal_id == principal_id,
            )
        )
        if result.scalar_one_or_none():
            raise InvalidCredentialsError("Principal already has a credential")

        # Auto-create principal if it doesn't exist (dev mode convenience)
        result = await session.execute(
            select(Principal).where(Principal.id == principal_id)
        )
        if not result.scalar_one_or_none():
            # Create principal for dev mode
            principal = Principal(
                id=principal_id,
                tenant_id=tenant_id,
                kind="user",
                status="active",
                display_name=username,  # Use username as display name
            )
            session.add(principal)
            logger.info(
                "auth.principal_auto_created",
                principal_id=str(principal_id),
                username=username,
                tenant_id=str(tenant_id),
            )

        # Hash password
        password_hash = _hash_key(password)

        credential = LocalCredential(
            id=uuid4(),
            tenant_id=tenant_id,
            principal_id=principal_id,
            username=username,
            password_hash=password_hash,
            status="active",
        )
        session.add(credential)

        logger.info(
            "auth.local_credential_created",
            username=username,
            principal_id=str(principal_id),
            tenant_id=str(tenant_id),
        )

        return credential

    async def validate_local_credential(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        username: str,
        password: str,
    ) -> LocalCredential:
        """Validate username/password and return credential if valid.

        Args:
            session: Database session
            tenant_id: Tenant ID
            username: Username
            password: Plain text password

        Returns:
            LocalCredential record if valid

        Raises:
            InvalidCredentialsError: If credentials are invalid
        """
        # Look up credential
        result = await session.execute(
            select(LocalCredential).where(
                LocalCredential.tenant_id == tenant_id,
                LocalCredential.username == username,
            )
        )
        credential = result.scalar_one_or_none()

        if not credential:
            logger.warning(
                "auth.local_credential_not_found",
                username=username,
                tenant_id=str(tenant_id),
            )
            raise InvalidCredentialsError("Invalid username or password")

        # Check status
        if credential.status != "active":
            logger.warning(
                "auth.local_credential_disabled",
                username=username,
            )
            raise InvalidCredentialsError("Account is disabled")

        # Verify password
        if not _verify_key(password, credential.password_hash):
            logger.warning(
                "auth.local_credential_invalid_password",
                username=username,
            )
            raise InvalidCredentialsError("Invalid username or password")

        # Update last login
        credential.last_login_at = utcnow()

        logger.debug(
            "auth.local_credential_validated",
            username=username,
            principal_id=str(credential.principal_id),
        )

        return credential

    # =========================================================================
    # Session Operations
    # =========================================================================

    def create_session(
        self,
        principal_id: UUID,
        tenant_id: UUID,
    ) -> Session:
        """Create a new session for an authenticated user.

        Args:
            principal_id: Authenticated principal ID
            tenant_id: Tenant ID

        Returns:
            Session object with session_id
        """
        session_id = secrets.token_urlsafe(32)
        now = utcnow()

        session = Session(
            session_id=session_id,
            principal_id=principal_id,
            tenant_id=tenant_id,
            created_at=now,
            expires_at=now + timedelta(hours=SESSION_DURATION_HOURS),
        )

        _session_store[session_id] = session

        logger.info(
            "auth.session_created",
            session_id=session_id[:8] + "...",
            principal_id=str(principal_id),
        )

        return session

    def validate_session(self, session_id: str) -> Session:
        """Validate a session ID and return session data.

        Args:
            session_id: Session ID from cookie

        Returns:
            Session object if valid

        Raises:
            InvalidSessionError: If session is invalid or expired
        """
        session = _session_store.get(session_id)

        if not session:
            raise InvalidSessionError("Session not found")

        # Check expiry
        if session.expires_at < utcnow():
            # Clean up expired session
            del _session_store[session_id]
            raise InvalidSessionError("Session has expired")

        logger.debug(
            "auth.session_validated",
            session_id=session_id[:8] + "...",
            principal_id=str(session.principal_id),
        )

        return session

    def destroy_session(self, session_id: str) -> bool:
        """Destroy a session (logout).

        Args:
            session_id: Session ID to destroy

        Returns:
            True if session was destroyed, False if not found
        """
        if session_id in _session_store:
            del _session_store[session_id]
            logger.info(
                "auth.session_destroyed",
                session_id=session_id[:8] + "...",
            )
            return True

        return False

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions from the store.

        Returns:
            Number of sessions removed
        """
        now = utcnow()
        expired = [
            sid for sid, session in _session_store.items() if session.expires_at < now
        ]

        for sid in expired:
            del _session_store[sid]

        if expired:
            logger.info(
                "auth.sessions_cleaned_up",
                count=len(expired),
            )

        return len(expired)
