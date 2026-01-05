"""Authentication models for API keys and OAuth tokens.

API Keys use a prefix+secret format:
- Full key: optaic_abc123def456.ghijklmnopqrstuvwxyz0123456789ABCD
- Prefix stored: optaic_abc123def456 (public identifier)
- Secret hashed: argon2 hash of full key

OAuth tokens are validated against OIDC provider (Keycloak).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .identity import Principal, Tenant


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class APIKey(Base):
    """API Key for SDK authentication.

    Keys are created with a prefix (public ID) and secret.
    Only the hash of the full key is stored - never the plaintext secret.

    Workflow:
    1. User creates key via API → receives full key ONCE
    2. SDK sends key in X-API-Key header
    3. API validates by hashing and comparing
    4. Key can be revoked or expires automatically
    """

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)

    # Key identification - prefix is publicly visible (e.g., "optaic_abc123def456")
    key_prefix: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    # Security - argon2id hash of the full key
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Scopes for fine-grained permissions (optional)
    scopes: Mapped[list] = mapped_column(JSON, default=list)

    # Status: active, revoked, expired
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Audit
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("principals.id"), nullable=True
    )
    revoked_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("principals.id"), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id])
    principal: Mapped["Principal"] = relationship(
        "Principal", foreign_keys=[principal_id]
    )

    __table_args__ = (
        Index("ix_api_keys_tenant_principal", "tenant_id", "principal_id"),
        Index("ix_api_keys_tenant_status", "tenant_id", "status"),
    )

    def is_valid(self) -> bool:
        """Check if key is valid (active and not expired)."""
        if self.status != "active":
            return False
        if self.expires_at and self.expires_at < utcnow():
            return False
        return True

    def __repr__(self) -> str:
        return f"<APIKey {self.key_prefix} ({self.status})>"


class OIDCProvider(Base):
    """OIDC Provider configuration (e.g., Keycloak).

    Supports multiple OIDC providers per tenant for federation.
    """

    __tablename__ = "oidc_providers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)

    # Provider identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer_url: Mapped[str] = mapped_column(String(512), nullable=False)

    # Client credentials (secret should be encrypted at rest in production)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )

    # Optional settings
    audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[list] = mapped_column(
        JSON, default=lambda: ["openid", "profile", "email"]
    )

    # Auto-create principals from OIDC claims
    auto_create_principals: Mapped[bool] = mapped_column(default=True)

    # Status
    enabled: Mapped[bool] = mapped_column(default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id])

    __table_args__ = (
        Index("ix_oidc_providers_tenant_issuer", "tenant_id", "issuer_url"),
    )

    def __repr__(self) -> str:
        return f"<OIDCProvider {self.name} ({self.issuer_url})>"


class LocalCredential(Base):
    """Local username/password credential for dev/testing.

    This is for GUI development without setting up OIDC.
    In production, use OIDC (Azure AD, Keycloak) instead.

    Passwords are hashed with argon2id.
    """

    __tablename__ = "local_credentials"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("principals.id"), unique=True, index=True
    )

    # Username must be unique within tenant
    username: Mapped[str] = mapped_column(String(255), nullable=False)

    # Argon2id hash of password
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status: active, disabled
    status: Mapped[str] = mapped_column(String(50), default="active")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[tenant_id])
    principal: Mapped["Principal"] = relationship(
        "Principal", foreign_keys=[principal_id]
    )

    __table_args__ = (
        Index("ix_local_cred_tenant_username", "tenant_id", "username", unique=True),
    )

    def __repr__(self) -> str:
        return f"<LocalCredential {self.username} ({self.status})>"


class OIDCPrincipalMapping(Base):
    """Maps OIDC subjects to principals.

    When a user authenticates via OIDC, their subject claim is mapped
    to a principal. This allows the same user to have different principals
    across tenants or to link multiple OIDC identities to one principal.
    """

    __tablename__ = "oidc_principal_mappings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("oidc_providers.id"), index=True
    )
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)

    # OIDC subject claim (unique per provider)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    # Cached claims (updated on each login)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claims_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    provider: Mapped["OIDCProvider"] = relationship(
        "OIDCProvider", foreign_keys=[provider_id]
    )
    principal: Mapped["Principal"] = relationship(
        "Principal", foreign_keys=[principal_id]
    )

    __table_args__ = (
        Index(
            "ix_oidc_mapping_provider_subject",
            "provider_id",
            "subject",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<OIDCPrincipalMapping {self.subject} -> {self.principal_id}>"
