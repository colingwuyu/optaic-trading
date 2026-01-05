"""Unit tests for AuthService.

Tests API key creation, validation, revocation, and OIDC principal mapping.
Uses real database sessions - NO MOCKS.
"""

import uuid

import pytest
from sqlalchemy import insert, select

from libs.core.auth import AuthService, InvalidAPIKeyError
from libs.db.models.identity import Principal, Tenant
from libs.db.session import AsyncSessionLocal


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def _seed_identity(session, tenant_id, principal_id):
    """Create tenant and principal for testing."""
    await session.execute(insert(Tenant).values(id=tenant_id, name="TestTenant"))
    await session.execute(
        insert(Principal).values(
            id=principal_id,
            tenant_id=tenant_id,
            kind="user",
            status="active",
            display_name="Test User",
            email="test@example.com",
        )
    )
    await session.flush()


# =============================================================================
# API Key Creation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_api_key_returns_full_key_and_record(db_session):
    """Test that create_api_key returns the full key and a valid record."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    full_key, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Test Key",
        description="A test API key",
        scopes=["read", "write"],
        expires_in_days=30,
    )

    # Verify full key format: prefix.secret
    assert "." in full_key
    assert full_key.startswith("optaic_")

    # Verify record
    assert api_key.id is not None
    assert api_key.tenant_id == tenant_id
    assert api_key.principal_id == principal_id
    assert api_key.name == "Test Key"
    assert api_key.description == "A test API key"
    assert api_key.scopes == ["read", "write"]
    assert api_key.status == "active"
    assert api_key.expires_at is not None
    assert api_key.key_prefix == full_key.rsplit(".", 1)[0]


@pytest.mark.asyncio
async def test_create_api_key_stores_hashed_secret(db_session):
    """Test that the full key is not stored, only the hash."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    full_key, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Secure Key",
    )

    # The key_hash should not contain the full key
    secret = full_key.split(".", 1)[1]
    assert secret not in api_key.key_hash
    assert full_key not in api_key.key_hash


@pytest.mark.asyncio
async def test_create_api_key_without_expiry(db_session):
    """Test creating a key without expiry date."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    _, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="No Expiry Key",
    )

    assert api_key.expires_at is None


@pytest.mark.asyncio
async def test_create_api_key_emits_activity(db_session):
    """Test that key creation emits an activity event."""
    from libs.db.models.activity import Activity, Outbox

    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    _, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Activity Key",
    )

    # Check activity was created
    activity_row = (
        await db_session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.resource_id == api_key.id,
                Activity.action == "api_key.created",
            )
        )
    ).first()
    assert activity_row is not None
    assert activity_row.resource_type == "APIKey"

    # Check outbox entry was created
    outbox_row = (
        await db_session.scalars(
            select(Outbox).where(
                Outbox.tenant_id == tenant_id,
                Outbox.topic == "activity",
            )
        )
    ).first()
    assert outbox_row is not None


# =============================================================================
# API Key Validation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_validate_api_key_succeeds_with_valid_key(db_session):
    """Test that validation succeeds with a valid key."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    full_key, created_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Valid Key",
    )
    await db_session.flush()

    # Validate the key
    validated_key = await auth_service.validate_api_key(db_session, full_key)

    assert validated_key.id == created_key.id
    assert validated_key.principal_id == principal_id
    assert validated_key.tenant_id == tenant_id
    assert validated_key.last_used_at is not None


@pytest.mark.asyncio
async def test_validate_api_key_fails_with_wrong_secret(db_session):
    """Test that validation fails with incorrect secret."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    full_key, _ = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Secret Test Key",
    )
    await db_session.flush()

    # Try with wrong secret
    prefix = full_key.rsplit(".", 1)[0]
    wrong_key = f"{prefix}.wrong_secret_12345678901234567890"

    with pytest.raises(InvalidAPIKeyError, match="Invalid API key"):
        await auth_service.validate_api_key(db_session, wrong_key)


@pytest.mark.asyncio
async def test_validate_api_key_fails_with_invalid_format(db_session):
    """Test that validation fails with malformed key."""
    auth_service = AuthService()

    with pytest.raises(InvalidAPIKeyError, match="Invalid key format"):
        await auth_service.validate_api_key(db_session, "no_dot_in_key")


@pytest.mark.asyncio
async def test_validate_api_key_fails_with_nonexistent_prefix(db_session):
    """Test that validation fails with unknown prefix."""
    auth_service = AuthService()

    with pytest.raises(InvalidAPIKeyError, match="API key not found"):
        await auth_service.validate_api_key(
            db_session, "optaic_nonexistent123.secret456"
        )


@pytest.mark.asyncio
async def test_validate_api_key_fails_with_revoked_key(db_session):
    """Test that validation fails for revoked keys."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    full_key, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Revokable Key",
    )
    await db_session.flush()

    # Revoke the key
    await auth_service.revoke_api_key(
        db_session,
        key_id=api_key.id,
        revoked_by=principal_id,
        tenant_id=tenant_id,
    )
    await db_session.flush()

    with pytest.raises(InvalidAPIKeyError, match="revoked"):
        await auth_service.validate_api_key(db_session, full_key)


@pytest.mark.asyncio
async def test_validate_api_key_fails_with_expired_key(db_session):
    """Test that validation fails for expired keys."""
    from datetime import datetime, timedelta, timezone

    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    full_key, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Expiring Key",
        expires_in_days=1,
    )

    # Manually set expiry to the past
    api_key.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.flush()

    with pytest.raises(InvalidAPIKeyError, match="expired"):
        await auth_service.validate_api_key(db_session, full_key)


# =============================================================================
# API Key Revocation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_revoke_api_key_sets_status_and_timestamps(db_session):
    """Test that revocation updates status and timestamps."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    _, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Revoke Test Key",
    )
    await db_session.flush()

    revoked_key = await auth_service.revoke_api_key(
        db_session,
        key_id=api_key.id,
        revoked_by=principal_id,
        tenant_id=tenant_id,
    )

    assert revoked_key.status == "revoked"
    assert revoked_key.revoked_at is not None
    assert revoked_key.revoked_by == principal_id


@pytest.mark.asyncio
async def test_revoke_api_key_emits_activity(db_session):
    """Test that revocation emits an activity event."""
    from libs.db.models.activity import Activity

    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    _, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Activity Revoke Key",
    )
    await db_session.flush()

    await auth_service.revoke_api_key(
        db_session,
        key_id=api_key.id,
        revoked_by=principal_id,
        tenant_id=tenant_id,
    )

    # Check revocation activity
    activity_row = (
        await db_session.scalars(
            select(Activity).where(
                Activity.tenant_id == tenant_id,
                Activity.resource_id == api_key.id,
                Activity.action == "api_key.revoked",
            )
        )
    ).first()
    assert activity_row is not None


@pytest.mark.asyncio
async def test_revoke_already_revoked_key_fails(db_session):
    """Test that revoking an already revoked key fails."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()
    _, api_key = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Double Revoke Key",
    )
    await db_session.flush()

    # First revoke succeeds
    await auth_service.revoke_api_key(
        db_session,
        key_id=api_key.id,
        revoked_by=principal_id,
        tenant_id=tenant_id,
    )
    await db_session.flush()

    # Second revoke fails
    with pytest.raises(InvalidAPIKeyError, match="already revoked"):
        await auth_service.revoke_api_key(
            db_session,
            key_id=api_key.id,
            revoked_by=principal_id,
            tenant_id=tenant_id,
        )


@pytest.mark.asyncio
async def test_revoke_nonexistent_key_fails(db_session):
    """Test that revoking a nonexistent key fails."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()

    with pytest.raises(InvalidAPIKeyError, match="not found"):
        await auth_service.revoke_api_key(
            db_session,
            key_id=uuid.uuid4(),  # Nonexistent
            revoked_by=principal_id,
            tenant_id=tenant_id,
        )


# =============================================================================
# API Key Listing Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_api_keys_returns_all_active_keys(db_session):
    """Test listing API keys for a principal."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()

    # Create multiple keys
    for i in range(3):
        await auth_service.create_api_key(
            db_session,
            tenant_id=tenant_id,
            principal_id=principal_id,
            name=f"Key {i}",
        )
    await db_session.flush()

    keys = await auth_service.list_api_keys(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
    )

    assert len(keys) == 3
    assert all(k.status == "active" for k in keys)


@pytest.mark.asyncio
async def test_list_api_keys_excludes_revoked_by_default(db_session):
    """Test that revoked keys are excluded by default."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()

    # Create keys
    _, key1 = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Active Key",
    )
    _, key2 = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Revoked Key",
    )
    await db_session.flush()

    # Revoke one key
    await auth_service.revoke_api_key(
        db_session,
        key_id=key2.id,
        revoked_by=principal_id,
        tenant_id=tenant_id,
    )
    await db_session.flush()

    # Default list excludes revoked
    keys = await auth_service.list_api_keys(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
    )
    assert len(keys) == 1
    assert keys[0].id == key1.id


@pytest.mark.asyncio
async def test_list_api_keys_includes_revoked_when_requested(db_session):
    """Test that revoked keys can be included."""
    tenant_id = uuid.uuid4()
    principal_id = uuid.uuid4()

    await _seed_identity(db_session, tenant_id, principal_id)

    auth_service = AuthService()

    # Create keys
    _, key1 = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Active Key",
    )
    _, key2 = await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        name="Revoked Key",
    )
    await db_session.flush()

    # Revoke one key
    await auth_service.revoke_api_key(
        db_session,
        key_id=key2.id,
        revoked_by=principal_id,
        tenant_id=tenant_id,
    )
    await db_session.flush()

    # List with revoked included
    keys = await auth_service.list_api_keys(
        db_session,
        tenant_id=tenant_id,
        principal_id=principal_id,
        include_revoked=True,
    )
    assert len(keys) == 2


@pytest.mark.asyncio
async def test_list_api_keys_filters_by_tenant(db_session):
    """Test that listing only returns keys for the specified tenant."""
    tenant_id_1 = uuid.uuid4()
    tenant_id_2 = uuid.uuid4()
    principal_id_1 = uuid.uuid4()
    principal_id_2 = uuid.uuid4()

    # Create two tenants with principals
    await _seed_identity(db_session, tenant_id_1, principal_id_1)
    await _seed_identity(db_session, tenant_id_2, principal_id_2)

    auth_service = AuthService()

    # Create keys in each tenant
    await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id_1,
        principal_id=principal_id_1,
        name="Tenant 1 Key",
    )
    await auth_service.create_api_key(
        db_session,
        tenant_id=tenant_id_2,
        principal_id=principal_id_2,
        name="Tenant 2 Key",
    )
    await db_session.flush()

    # List keys for tenant 1
    keys = await auth_service.list_api_keys(
        db_session,
        tenant_id=tenant_id_1,
    )
    assert len(keys) == 1
    assert keys[0].tenant_id == tenant_id_1
