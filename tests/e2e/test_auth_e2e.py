"""End-to-End Authentication Tests - Using Python SDK.

These tests verify the authentication system works correctly
end-to-end through the SDK -> API -> Service -> Database stack.

Test Scenarios:
1. API Key CRUD (create, list, get, revoke)
2. API Key Authentication
3. Dev Mode Authentication (backwards compatibility)
4. Current User Info Endpoint
5. Session Login/Logout (dev mode)

CRITICAL PRINCIPLE: SDK-ONLY TESTING
=====================================
E2E tests must ONLY use the SDK. NO direct database access allowed.
NO MOCKS - All tests use real API endpoints via SDK.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from libs.sdk_py import AsyncPlatformClient


# =============================================================================
# FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Create an AsyncPlatformClient using ASGI transport for testing."""
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    client = AsyncPlatformClient(
        base_url="http://test",
        client=httpx_client,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="function")
async def auth_test_setup(sdk_client: AsyncPlatformClient):
    """Set up tenant and principal for auth testing."""
    tenant_id = uuid4()
    principal_id = uuid4()

    sdk_client.set_principal_id(principal_id)
    sdk_client.set_tenant_id(tenant_id)

    # Create tenant (this creates the principal implicitly in dev mode)
    tenant_result = await sdk_client.tenants.create(
        name=f"AuthTestTenant-{tenant_id}",
    )

    return {
        "client": sdk_client,
        "tenant_id": UUID(tenant_result["id"]),
        "principal_id": principal_id,
    }


# =============================================================================
# API KEY CRUD TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_create_api_key(auth_test_setup):
    """Test creating an API key returns the full key and metadata."""
    client = auth_test_setup["client"]

    # Create API key via SDK
    result = await client.auth.create_api_key(
        name="Test SDK Key",
        description="Key created via SDK for testing",
        scopes=["read", "write"],
        expires_in_days=30,
    )

    # Verify response contains full key (shown only once)
    assert "id" in result
    assert "key" in result
    assert result["key"].startswith("optaic_")
    assert "." in result["key"]  # prefix.secret format

    # Verify metadata
    assert result["name"] == "Test SDK Key"
    assert result["description"] == "Key created via SDK for testing"
    assert result["scopes"] == ["read", "write"]
    assert result["status"] == "active"
    assert result["expires_at"] is not None
    assert result["key_prefix"] == result["key"].rsplit(".", 1)[0]


@pytest.mark.asyncio
async def test_create_api_key_without_expiry(auth_test_setup):
    """Test creating an API key without expiry."""
    client = auth_test_setup["client"]

    result = await client.auth.create_api_key(
        name="No Expiry Key",
    )

    assert result["expires_at"] is None
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_list_api_keys(auth_test_setup):
    """Test listing API keys for the current principal."""
    client = auth_test_setup["client"]

    # Create multiple keys
    for i in range(3):
        await client.auth.create_api_key(name=f"List Test Key {i}")

    # List keys
    result = await client.auth.list_api_keys()

    assert "items" in result
    assert "total" in result
    assert result["total"] >= 3
    assert len(result["items"]) >= 3

    # Verify keys don't expose full secret
    for key in result["items"]:
        assert "key_prefix" in key
        assert "key" not in key  # Full key should not be in list
        assert "key_hash" not in key  # Hash should not be exposed


@pytest.mark.asyncio
async def test_get_api_key_details(auth_test_setup):
    """Test getting details for a specific API key."""
    client = auth_test_setup["client"]

    # Create a key
    created = await client.auth.create_api_key(
        name="Detail Test Key",
        description="Test description",
    )
    key_id = created["id"]

    # Get details
    result = await client.auth.get_api_key(key_id)

    assert result["id"] == key_id
    assert result["name"] == "Detail Test Key"
    assert result["description"] == "Test description"
    assert result["key_prefix"] == created["key_prefix"]
    assert "key" not in result  # Full key not returned on get


@pytest.mark.asyncio
async def test_revoke_api_key(auth_test_setup):
    """Test revoking an API key."""
    client = auth_test_setup["client"]

    # Create a key
    created = await client.auth.create_api_key(name="Revoke Test Key")
    key_id = created["id"]

    # Revoke the key
    result = await client.auth.revoke_api_key(key_id)

    assert result["id"] == key_id
    assert result["status"] == "revoked"
    assert result["revoked_at"] is not None


@pytest.mark.asyncio
async def test_revoked_key_excluded_from_list(auth_test_setup):
    """Test that revoked keys are excluded from list by default."""
    client = auth_test_setup["client"]

    # Create two keys
    key1 = await client.auth.create_api_key(name="Active Key")
    key2 = await client.auth.create_api_key(name="Will Be Revoked")

    # Revoke one
    await client.auth.revoke_api_key(key2["id"])

    # List without include_revoked
    result = await client.auth.list_api_keys()

    key_ids = [k["id"] for k in result["items"]]
    assert key1["id"] in key_ids
    assert key2["id"] not in key_ids


@pytest.mark.asyncio
async def test_list_api_keys_with_revoked(auth_test_setup):
    """Test listing API keys including revoked ones."""
    client = auth_test_setup["client"]

    # Create and revoke a key
    key1 = await client.auth.create_api_key(name="Active Key")
    key2 = await client.auth.create_api_key(name="Revoked Key")
    await client.auth.revoke_api_key(key2["id"])

    # List with include_revoked
    result = await client.auth.list_api_keys(include_revoked=True)

    key_ids = [k["id"] for k in result["items"]]
    assert key1["id"] in key_ids
    assert key2["id"] in key_ids


# =============================================================================
# API KEY AUTHENTICATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_authenticate_with_api_key(auth_test_setup):
    """Test authenticating with an API key instead of dev headers."""
    client = auth_test_setup["client"]
    principal_id = auth_test_setup["principal_id"]
    tenant_id = auth_test_setup["tenant_id"]

    # Create an API key
    created = await client.auth.create_api_key(name="Auth Test Key")
    full_key = created["key"]

    # Create a new client that uses the API key
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    api_key_client = AsyncPlatformClient(
        base_url="http://test",
        api_key=full_key,
        client=httpx_client,
    )

    try:
        # Verify we can authenticate with the API key
        user_info = await api_key_client.auth.get_current_user()

        assert str(user_info["principal_id"]) == str(principal_id)
        assert str(user_info["tenant_id"]) == str(tenant_id)
        assert user_info["auth_method"] == "api_key"
    finally:
        await api_key_client.close()


@pytest.mark.asyncio
async def test_api_key_auth_can_create_resources(auth_test_setup):
    """Test that API key authenticated clients can perform operations."""
    client = auth_test_setup["client"]

    # First get the root resource via dev auth
    tenant_result = await client.tenants.get(auth_test_setup["tenant_id"])
    root_resource_id = tenant_result.get("root_resource_id")

    # Create an API key
    created = await client.auth.create_api_key(name="Resource Create Key")
    full_key = created["key"]

    # Create a new client using the API key
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    api_key_client = AsyncPlatformClient(
        base_url="http://test",
        api_key=full_key,
        client=httpx_client,
    )

    try:
        # Use API key client to create a resource
        space = await api_key_client.resources.create(
            resource_type="Space",
            parent_id=root_resource_id,
            name="API Key Created Space",
        )

        assert space["name"] == "API Key Created Space"
        assert space["type"] == "Space"
    finally:
        await api_key_client.close()


@pytest.mark.asyncio
async def test_revoked_api_key_fails_authentication(auth_test_setup):
    """Test that revoked API keys cannot authenticate."""
    client = auth_test_setup["client"]

    # Create and revoke a key
    created = await client.auth.create_api_key(name="Soon Revoked Key")
    full_key = created["key"]
    await client.auth.revoke_api_key(created["id"])

    # Try to use the revoked key
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    revoked_client = AsyncPlatformClient(
        base_url="http://test",
        api_key=full_key,
        client=httpx_client,
    )

    try:
        # Should fail authentication
        with pytest.raises(Exception) as exc_info:
            await revoked_client.auth.get_current_user()

        # Should get 401 Unauthorized
        assert "401" in str(exc_info.value) or "revoked" in str(exc_info.value).lower()
    finally:
        await revoked_client.close()


@pytest.mark.asyncio
async def test_invalid_api_key_fails_authentication():
    """Test that invalid API keys fail authentication."""
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    invalid_client = AsyncPlatformClient(
        base_url="http://test",
        api_key="optaic_invalid123.fakesecret456789012345678901234",
        client=httpx_client,
    )

    try:
        with pytest.raises(Exception) as exc_info:
            await invalid_client.auth.get_current_user()

        # Should get 401 Unauthorized
        assert "401" in str(exc_info.value)
    finally:
        await invalid_client.close()


# =============================================================================
# DEV MODE AUTHENTICATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_dev_auth_works_with_headers(auth_test_setup):
    """Test that dev mode auth with X-Principal-Id headers still works."""
    client = auth_test_setup["client"]
    principal_id = auth_test_setup["principal_id"]
    tenant_id = auth_test_setup["tenant_id"]

    # The test fixture uses dev auth, verify it works
    user_info = await client.auth.get_current_user()

    assert str(user_info["principal_id"]) == str(principal_id)
    assert str(user_info["tenant_id"]) == str(tenant_id)
    # Dev auth should be marked as such
    assert user_info["auth_method"] in ["dev", "unknown"]


@pytest.mark.asyncio
async def test_dev_auth_can_perform_operations(auth_test_setup):
    """Test that dev auth can still perform all operations."""
    client = auth_test_setup["client"]

    # Get root resource
    tenant_result = await client.tenants.get(auth_test_setup["tenant_id"])
    root_resource_id = tenant_result.get("root_resource_id")

    # Create resources using dev auth
    space = await client.resources.create(
        resource_type="Space",
        parent_id=root_resource_id,
        name="Dev Auth Space",
    )

    assert space["name"] == "Dev Auth Space"

    # List resources
    children = await client.resources.list_children(root_resource_id)
    assert any(c["name"] == "Dev Auth Space" for c in children["items"])


# =============================================================================
# CURRENT USER ENDPOINT TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_get_current_user_with_dev_auth(auth_test_setup):
    """Test /auth/me endpoint with dev authentication."""
    client = auth_test_setup["client"]
    principal_id = auth_test_setup["principal_id"]
    tenant_id = auth_test_setup["tenant_id"]

    result = await client.auth.get_current_user()

    assert "principal_id" in result
    assert "tenant_id" in result
    assert "kind" in result
    assert "auth_method" in result

    assert str(result["principal_id"]) == str(principal_id)
    assert str(result["tenant_id"]) == str(tenant_id)


@pytest.mark.asyncio
async def test_get_current_user_with_api_key(auth_test_setup):
    """Test /auth/me endpoint with API key authentication."""
    client = auth_test_setup["client"]

    # Create an API key
    created = await client.auth.create_api_key(name="Me Endpoint Key")
    full_key = created["key"]

    # Use the API key
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    api_key_client = AsyncPlatformClient(
        base_url="http://test",
        api_key=full_key,
        client=httpx_client,
    )

    try:
        result = await api_key_client.auth.get_current_user()

        assert result["auth_method"] == "api_key"
        assert str(result["principal_id"]) == str(auth_test_setup["principal_id"])
    finally:
        await api_key_client.close()


# =============================================================================
# MULTIPLE API KEYS TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_principal_can_have_multiple_keys(auth_test_setup):
    """Test that a principal can have multiple active API keys."""
    client = auth_test_setup["client"]
    principal_id = auth_test_setup["principal_id"]

    # Create multiple keys
    keys = []
    for i in range(3):
        key = await client.auth.create_api_key(name=f"Multi Key {i}")
        keys.append(key)

    # Verify all keys work
    for key in keys:
        httpx_client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        )
        key_client = AsyncPlatformClient(
            base_url="http://test",
            api_key=key["key"],
            client=httpx_client,
        )

        try:
            user_info = await key_client.auth.get_current_user()
            assert str(user_info["principal_id"]) == str(principal_id)
        finally:
            await key_client.close()


@pytest.mark.asyncio
async def test_revoking_one_key_doesnt_affect_others(auth_test_setup):
    """Test that revoking one key doesn't affect other keys."""
    client = auth_test_setup["client"]

    # Create two keys
    key1 = await client.auth.create_api_key(name="Key 1")
    key2 = await client.auth.create_api_key(name="Key 2")

    # Revoke key 1
    await client.auth.revoke_api_key(key1["id"])

    # Key 2 should still work
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    key2_client = AsyncPlatformClient(
        base_url="http://test",
        api_key=key2["key"],
        client=httpx_client,
    )

    try:
        # Key 2 should still authenticate
        user_info = await key2_client.auth.get_current_user()
        assert user_info["auth_method"] == "api_key"
    finally:
        await key2_client.close()


# =============================================================================
# SESSION LOGIN/LOGOUT TESTS (DEV MODE)
# =============================================================================


@pytest.mark.asyncio
async def test_register_local_credential(auth_test_setup):
    """Test registering a local username/password credential."""
    client = auth_test_setup["client"]
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    # Register via direct HTTP call (not SDK method yet)
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    response = await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "testuser",
            "password": "testpass123",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "testuser"
    assert str(data["principal_id"]) == str(principal_id)
    assert data["message"] == "Registration successful"

    await httpx_client.aclose()


@pytest.mark.asyncio
async def test_login_with_username_password(auth_test_setup):
    """Test logging in with username and password."""
    client = auth_test_setup["client"]
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # First register a credential
    await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "loginuser",
            "password": "loginpass123",
        },
    )

    # Now login
    response = await httpx_client.post(
        "/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": "loginuser",
            "password": "loginpass123",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert str(data["principal_id"]) == str(principal_id)
    assert str(data["tenant_id"]) == str(tenant_id)
    assert data["message"] == "Login successful"
    assert "expires_at" in data

    # Check that session cookie was set
    assert "optaic_session" in response.cookies

    await httpx_client.aclose()


@pytest.mark.asyncio
async def test_session_cookie_authentication(auth_test_setup):
    """Test that session cookie authenticates subsequent requests."""
    client = auth_test_setup["client"]
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # Register and login
    await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "sessionuser",
            "password": "sessionpass123",
        },
    )

    login_response = await httpx_client.post(
        "/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": "sessionuser",
            "password": "sessionpass123",
        },
    )

    session_cookie = login_response.cookies.get("optaic_session")
    assert session_cookie is not None

    # Create new client with session cookie set
    session_httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"optaic_session": session_cookie},
    )

    # Use session cookie to get session info
    response = await session_httpx_client.get("/auth/session")

    assert response.status_code == 200
    data = response.json()
    assert str(data["principal_id"]) == str(principal_id)
    assert str(data["tenant_id"]) == str(tenant_id)
    assert data["auth_method"] == "session"

    await httpx_client.aclose()
    await session_httpx_client.aclose()


@pytest.mark.asyncio
async def test_session_cookie_can_access_protected_endpoints(auth_test_setup):
    """Test that session cookie can access protected API endpoints."""
    client = auth_test_setup["client"]
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # Register and login
    await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "protecteduser",
            "password": "protectedpass123",
        },
    )

    login_response = await httpx_client.post(
        "/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": "protecteduser",
            "password": "protectedpass123",
        },
    )

    session_cookie = login_response.cookies.get("optaic_session")

    # Create new client with session cookie set
    session_httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"optaic_session": session_cookie},
    )

    # Use session to access /auth/me (protected endpoint)
    response = await session_httpx_client.get("/auth/me")

    assert response.status_code == 200
    data = response.json()
    assert str(data["principal_id"]) == str(principal_id)
    assert data["auth_method"] == "session"

    await httpx_client.aclose()
    await session_httpx_client.aclose()


@pytest.mark.asyncio
async def test_logout_clears_session(auth_test_setup):
    """Test that logout clears the session."""
    client = auth_test_setup["client"]
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # Register and login
    await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "logoutuser",
            "password": "logoutpass123",
        },
    )

    login_response = await httpx_client.post(
        "/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": "logoutuser",
            "password": "logoutpass123",
        },
    )

    session_cookie = login_response.cookies.get("optaic_session")

    # Create client with session cookie for logout
    session_httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"optaic_session": session_cookie},
    )

    # Logout
    logout_response = await session_httpx_client.post("/auth/logout")

    assert logout_response.status_code == 200
    assert logout_response.json()["message"] == "Logged out successfully"

    # Try to use the old session - should fail
    # Create a new client with the same (now invalid) cookie
    invalid_session_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"optaic_session": session_cookie},
    )
    response = await invalid_session_client.get("/auth/session")

    assert response.status_code == 401

    await httpx_client.aclose()
    await session_httpx_client.aclose()
    await invalid_session_client.aclose()


@pytest.mark.asyncio
async def test_invalid_credentials_fail_login(auth_test_setup):
    """Test that invalid credentials fail login."""
    client = auth_test_setup["client"]
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # Register a credential
    await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "invaliduser",
            "password": "correctpass123",
        },
    )

    # Try to login with wrong password
    response = await httpx_client.post(
        "/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": "invaliduser",
            "password": "wrongpassword",
        },
    )

    assert response.status_code == 401

    await httpx_client.aclose()


@pytest.mark.asyncio
async def test_nonexistent_user_fails_login(auth_test_setup):
    """Test that nonexistent username fails login."""
    tenant_id = auth_test_setup["tenant_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    response = await httpx_client.post(
        "/auth/login",
        json={
            "tenant_id": str(tenant_id),
            "username": "nonexistentuser",
            "password": "anypassword",
        },
    )

    assert response.status_code == 401

    await httpx_client.aclose()


@pytest.mark.asyncio
async def test_duplicate_username_registration_fails(auth_test_setup):
    """Test that registering the same username twice fails."""
    tenant_id = auth_test_setup["tenant_id"]
    principal_id = auth_test_setup["principal_id"]

    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # First registration
    response1 = await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(principal_id),
            "username": "duplicateuser",
            "password": "pass123456",
        },
    )
    assert response1.status_code == 201

    # Second registration with same username should fail
    response2 = await httpx_client.post(
        "/auth/register",
        json={
            "tenant_id": str(tenant_id),
            "principal_id": str(uuid4()),  # Different principal
            "username": "duplicateuser",
            "password": "pass654321",
        },
    )
    assert response2.status_code == 400

    await httpx_client.aclose()
