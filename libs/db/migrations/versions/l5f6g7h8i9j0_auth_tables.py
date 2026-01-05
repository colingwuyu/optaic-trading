"""Add authentication tables for API keys and OIDC.

Revision ID: l5f6g7h8i9j0
Revises: k4e5f6g7h8i9
Create Date: 2026-01-05 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "l5f6g7h8i9j0"
down_revision: Union[str, None] = "k4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create api_keys table
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("key_prefix", sa.String(50), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["principals.id"]),
        sa.ForeignKeyConstraint(["revoked_by"], ["principals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"], unique=True)
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_principal_id", "api_keys", ["principal_id"])
    op.create_index("ix_api_keys_status", "api_keys", ["status"])
    op.create_index(
        "ix_api_keys_tenant_principal", "api_keys", ["tenant_id", "principal_id"]
    )
    op.create_index("ix_api_keys_tenant_status", "api_keys", ["tenant_id", "status"])

    # Create oidc_providers table
    op.create_table(
        "oidc_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("issuer_url", sa.String(512), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_encrypted", sa.String(512), nullable=True),
        sa.Column("audience", sa.String(255), nullable=True),
        sa.Column(
            "scopes",
            sa.JSON(),
            nullable=False,
            server_default='["openid", "profile", "email"]',
        ),
        sa.Column(
            "auto_create_principals",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_providers_tenant_id", "oidc_providers", ["tenant_id"])
    op.create_index(
        "ix_oidc_providers_tenant_issuer",
        "oidc_providers",
        ["tenant_id", "issuer_url"],
    )

    # Create oidc_principal_mappings table
    op.create_table(
        "oidc_principal_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("claims_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["oidc_providers.id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oidc_principal_mappings_provider_id",
        "oidc_principal_mappings",
        ["provider_id"],
    )
    op.create_index(
        "ix_oidc_principal_mappings_principal_id",
        "oidc_principal_mappings",
        ["principal_id"],
    )
    op.create_index(
        "ix_oidc_mapping_provider_subject",
        "oidc_principal_mappings",
        ["provider_id", "subject"],
        unique=True,
    )

    # Create local_credentials table for dev/testing password auth
    op.create_table(
        "local_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_local_credentials_tenant_id", "local_credentials", ["tenant_id"]
    )
    op.create_index(
        "ix_local_credentials_principal_id",
        "local_credentials",
        ["principal_id"],
        unique=True,
    )
    op.create_index(
        "ix_local_cred_tenant_username",
        "local_credentials",
        ["tenant_id", "username"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("local_credentials")
    op.drop_table("oidc_principal_mappings")
    op.drop_table("oidc_providers")
    op.drop_table("api_keys")
