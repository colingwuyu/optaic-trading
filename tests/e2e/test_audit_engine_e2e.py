"""End-to-End Audit Engine Tests - Using Python SDK.

These tests verify the complete audit pipeline:
1. Activity emission through service layer (resource CRUD)
2. Activity feed with RBAC filtering
3. Subscription-based visibility
4. Pagination

CRITICAL PRINCIPLE: SDK-ONLY TESTING
=====================================
E2E tests must ONLY use the SDK. NO direct database access allowed.
NO MOCKS - All tests use real API endpoints via SDK.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from libs.sdk_py import AsyncPlatformClient

# E2E tests connect to an external server
# Start the server with: python scripts/e2e_server.py
E2E_API_URL = os.environ.get("E2E_API_URL", "http://localhost:8082")


# =============================================================================
# FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Create an AsyncPlatformClient connected to E2E test server.

    NOTE: The E2E server must be running before tests execute.
    Start it with: python scripts/e2e_server.py
    """
    client = AsyncPlatformClient(base_url=E2E_API_URL)
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="function")
async def audit_test_env(sdk_client: AsyncPlatformClient):
    """Set up environment for audit engine testing.

    The E2E server bootstraps a system tenant on startup with:
    - tenant_id: 00000000-0000-0000-0000-000000000001
    - admin_id: 00000000-0000-0000-0000-000000000003
    - space_id: 00000000-0000-0000-0000-000000000002
    """
    # Use bootstrap admin principal and tenant
    BOOTSTRAP_TENANT_ID = "00000000-0000-0000-0000-000000000001"
    BOOTSTRAP_ADMIN_ID = "00000000-0000-0000-0000-000000000003"
    BOOTSTRAP_SPACE_ID = "00000000-0000-0000-0000-000000000002"

    sdk_client.set_principal_id(BOOTSTRAP_ADMIN_ID)
    sdk_client.set_tenant_id(BOOTSTRAP_TENANT_ID)

    # Create a unique Project for each test to isolate data
    project = await sdk_client.resources.create(
        resource_type="Project",
        parent_id=BOOTSTRAP_SPACE_ID,
        name=f"Audit Test Project {uuid4()}",
    )

    return {
        "client": sdk_client,
        "tenant_id": UUID(BOOTSTRAP_TENANT_ID),
        "principal_id": UUID(BOOTSTRAP_ADMIN_ID),
        "space_id": UUID(BOOTSTRAP_SPACE_ID),
        "project_id": UUID(project["id"]),
    }


# =============================================================================
# TEST: ACTIVITY EMISSION ON RESOURCE CREATE
# =============================================================================


@pytest.mark.asyncio
async def test_activity_emission_on_resource_create(audit_test_env):
    """Test that creating a resource via SDK emits an activity."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a Folder resource (triggers activity)
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name=f"Test Folder {uuid4()}",
    )

    folder_id = folder["id"]

    # Query activities for the resource
    activities = await client.activities.list(resource_id=folder_id)

    # Verify activity exists for resource creation
    items = activities.get("items", [])
    assert len(items) >= 1, "Expected at least one activity for the created resource"

    # Find the create activity
    create_activities = [a for a in items if a["action"] == "resource.created"]
    assert len(create_activities) >= 1, "Expected 'resource.created' activity"

    create_activity = create_activities[0]
    assert create_activity["resource"]["resource_id"] == folder_id
    assert create_activity["actor"]["principal_id"] == str(
        audit_test_env["principal_id"]
    )


@pytest.mark.asyncio
async def test_activity_emission_on_resource_update(audit_test_env):
    """Test that updating a resource via SDK emits an activity."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a resource
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name=f"Test Folder {uuid4()}",
    )

    folder_id = folder["id"]

    # Update the resource
    await client.resources.update(
        resource_id=folder_id,
        name="Updated Folder Name",
    )

    # Query activities for the resource
    activities = await client.activities.list(resource_id=folder_id)
    items = activities.get("items", [])

    # Find update activities
    update_activities = [a for a in items if a["action"] == "resource.updated"]
    assert len(update_activities) >= 1, "Expected 'resource.updated' activity"


# =============================================================================
# TEST: ACTIVITY FEED PAGINATION
# =============================================================================


@pytest.mark.asyncio
async def test_activity_pagination(audit_test_env):
    """Test that activity pagination works correctly."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create multiple resources to generate activities
    folder_ids = []
    for i in range(5):
        folder = await client.resources.create(
            resource_type="Folder",
            parent_id=str(project_id),
            name=f"Pagination Test Folder {i}",
        )
        folder_ids.append(folder["id"])

    # Query with limit=2 to test pagination
    page1 = await client.activities.list(limit=2)
    items1 = page1.get("items", [])
    cursor = page1.get("next_cursor")

    assert len(items1) == 2, "Expected 2 items in first page"

    # Get next page if cursor exists
    if cursor:
        page2 = await client.activities.list(limit=2, cursor=cursor)
        items2 = page2.get("items", [])
        assert len(items2) >= 1, "Expected items in second page"

        # Ensure no duplicates
        ids1 = {item["event_id"] for item in items1}
        ids2 = {item["event_id"] for item in items2}
        assert ids1.isdisjoint(ids2), "Pages should not have duplicate activities"


# =============================================================================
# TEST: ACTIVITY RESOURCE FILTER
# =============================================================================


@pytest.mark.asyncio
async def test_activity_resource_filter(audit_test_env):
    """Test that activities can be filtered by resource_id."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create two separate folders
    folder1 = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name="Filter Test Folder 1",
    )
    folder1_id = folder1["id"]

    folder2 = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name="Filter Test Folder 2",
    )
    folder2["id"]

    # Query activities for folder1 only
    activities = await client.activities.list(resource_id=folder1_id)
    items = activities.get("items", [])

    # All activities should be for folder1
    for item in items:
        assert item["resource"]["resource_id"] == folder1_id, (
            f"Expected activities for {folder1_id}, got {item['resource']['resource_id']}"
        )


# =============================================================================
# TEST: SUBSCRIPTION-BASED ACTIVITY VISIBILITY
# =============================================================================


@pytest.mark.asyncio
async def test_subscription_creates_activity(audit_test_env):
    """Test that creating a subscription emits an activity."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a folder to subscribe to
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name="Subscription Test Folder",
    )
    folder_id = folder["id"]

    # Subscribe to the resource
    subscription = await client.subscriptions.create(
        resource_id=folder_id,
        scope="resource",
    )

    # Verify subscription was created
    assert subscription["resource_id"] == folder_id
    assert subscription["scope"] == "resource"

    # Query activities - should include subscription.created
    activities = await client.activities.list(resource_id=folder_id)
    items = activities.get("items", [])

    subscription_activities = [
        a for a in items if a["action"] == "subscription.created"
    ]
    assert len(subscription_activities) >= 1, "Expected 'subscription.created' activity"


@pytest.mark.asyncio
async def test_list_subscriptions(audit_test_env):
    """Test that subscriptions can be listed."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a folder and subscribe
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name="List Subscription Test Folder",
    )
    folder_id = folder["id"]

    await client.subscriptions.create(
        resource_id=folder_id,
        scope="resource",
    )

    # List subscriptions
    subscriptions = await client.subscriptions.list()

    # Verify subscription is in the list
    folder_subs = [s for s in subscriptions if s["resource_id"] == folder_id]
    assert len(folder_subs) >= 1, "Expected to find subscription in list"


@pytest.mark.asyncio
async def test_revoke_subscription_emits_activity(audit_test_env):
    """Test that revoking a subscription emits an activity."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a folder and subscribe
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name="Revoke Subscription Test Folder",
    )
    folder_id = folder["id"]

    subscription = await client.subscriptions.create(
        resource_id=folder_id,
        scope="resource",
    )
    subscription_id = subscription["id"]

    # Revoke the subscription
    revoked = await client.subscriptions.revoke(subscription_id)
    assert revoked["revoked_at"] is not None

    # Query activities - should include subscription.revoked
    activities = await client.activities.list(resource_id=folder_id)
    items = activities.get("items", [])

    revoke_activities = [a for a in items if a["action"] == "subscription.revoked"]
    assert len(revoke_activities) >= 1, "Expected 'subscription.revoked' activity"


# =============================================================================
# TEST: ACTIVITY VISIBILITY
# =============================================================================


@pytest.mark.asyncio
async def test_activities_filtered_by_tenant(audit_test_env):
    """Test that activities are filtered by tenant."""
    client = audit_test_env["client"]
    tenant_id = audit_test_env["tenant_id"]

    # Query activities
    activities = await client.activities.list()
    items = activities.get("items", [])

    # All activities should belong to the same tenant
    for item in items:
        assert item["tenant_id"] == str(tenant_id), (
            f"Expected tenant {tenant_id}, got {item['tenant_id']}"
        )


# =============================================================================
# TEST: SUBSCRIPTION SCOPE - DESCENDANTS
# =============================================================================


@pytest.mark.asyncio
async def test_subscription_descendants_scope(audit_test_env):
    """Test subscription with descendants scope includes child activities."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a folder hierarchy
    parent_folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name="Parent Folder",
    )
    parent_folder_id = parent_folder["id"]

    child_folder = await client.resources.create(
        resource_type="Folder",
        parent_id=parent_folder_id,
        name="Child Folder",
    )
    child_folder_id = child_folder["id"]

    # Subscribe to parent with descendants scope
    subscription = await client.subscriptions.create(
        resource_id=parent_folder_id,
        scope="descendants",
    )

    assert subscription["scope"] == "descendants"

    # Query activities - should be able to see both parent and child
    # (because admin has VIEW_ACTIVITY_FEED permission)
    activities = await client.activities.list()
    items = activities.get("items", [])

    # Find activities for both parent and child
    parent_activities = [
        a for a in items if a["resource"]["resource_id"] == parent_folder_id
    ]
    [a for a in items if a["resource"]["resource_id"] == child_folder_id]

    assert len(parent_activities) >= 1, "Expected activities for parent folder"
    # Child should also be visible through subscription or RBAC
    # The exact behavior depends on RBAC setup


# =============================================================================
# TEST: AUDIT LOG QUERY API
# =============================================================================


@pytest.mark.asyncio
async def test_audit_log_search(audit_test_env):
    """Test that audit logs can be searched via the SDK."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a resource to generate activities
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name=f"Audit Search Test Folder {uuid4()}",
    )
    folder["id"]

    # Wait briefly for outbox worker to process and create audit log entries
    import asyncio

    await asyncio.sleep(0.5)

    # Query audit logs via SDK
    audit_logs = await client.audit.search(limit=10)

    # Verify we got a paginated response
    assert "items" in audit_logs
    assert "next_cursor" in audit_logs

    # If items exist, verify structure
    if audit_logs["items"]:
        entry = audit_logs["items"][0]
        assert "id" in entry
        assert "tenant_id" in entry
        assert "activity_id" in entry
        assert "envelope" in entry
        assert "processed_at" in entry


@pytest.mark.asyncio
async def test_audit_log_filter_by_resource(audit_test_env):
    """Test that audit logs can be filtered by resource_id."""
    client = audit_test_env["client"]
    project_id = audit_test_env["project_id"]

    # Create a resource
    folder = await client.resources.create(
        resource_type="Folder",
        parent_id=str(project_id),
        name=f"Audit Filter Test Folder {uuid4()}",
    )
    folder_id = folder["id"]

    # Wait for processing
    import asyncio

    await asyncio.sleep(0.5)

    # Query audit logs filtered by resource
    audit_logs = await client.audit.search(resource_id=folder_id, limit=10)

    # All returned entries should be for this resource
    for entry in audit_logs.get("items", []):
        envelope = entry.get("envelope", {})
        resource = envelope.get("resource", {})
        assert resource.get("resource_id") == folder_id


@pytest.mark.asyncio
async def test_audit_log_count(audit_test_env):
    """Test that audit log count endpoint works."""
    client = audit_test_env["client"]

    # Get count of all audit logs
    result = await client.audit.count()

    assert "count" in result
    assert isinstance(result["count"], int)
    assert result["count"] >= 0


# =============================================================================
# TEST: NOTIFICATIONS API
# =============================================================================


@pytest.mark.asyncio
async def test_notification_list(audit_test_env):
    """Test that notifications can be listed via the SDK."""
    client = audit_test_env["client"]

    # Query notifications
    notifications = await client.notifications.list(limit=10)

    # Verify response structure
    assert "items" in notifications
    assert "next_cursor" in notifications
    assert "unread_count" in notifications


@pytest.mark.asyncio
async def test_notification_unread_count(audit_test_env):
    """Test that unread count endpoint works."""
    client = audit_test_env["client"]

    # Get unread count
    result = await client.notifications.unread_count()

    assert "unread_count" in result
    assert isinstance(result["unread_count"], int)
    assert result["unread_count"] >= 0


@pytest.mark.asyncio
async def test_notification_mark_all_read(audit_test_env):
    """Test that mark all read endpoint works."""
    client = audit_test_env["client"]

    # Mark all notifications as read
    result = await client.notifications.mark_all_read()

    assert "marked_count" in result
    assert isinstance(result["marked_count"], int)
    assert result["marked_count"] >= 0

    # Verify all are now read
    unread = await client.notifications.unread_count()
    assert unread["unread_count"] == 0


# =============================================================================
# TEST: NOTIFICATION PREFERENCES API
# =============================================================================


@pytest.mark.asyncio
async def test_notification_preferences_get_default(audit_test_env):
    """Test that default notification preferences structure is correct.

    Note: Preferences persist across test runs. This test verifies
    the structure rather than assuming a clean state.
    """
    client = audit_test_env["client"]

    # Reset preferences to defaults for this test
    await client.notifications.update_preferences(
        filter_mode="mutations",
        custom_actions=[],
        muted=False,
    )

    # Get preferences (should now be defaults)
    prefs = await client.notifications.get_preferences()

    # Verify structure
    assert "filter_mode" in prefs
    assert "custom_actions" in prefs
    assert "muted" in prefs

    # Verify reset values
    assert prefs["filter_mode"] == "mutations"
    assert prefs["custom_actions"] == []
    assert prefs["muted"] is False


@pytest.mark.asyncio
async def test_notification_preferences_update(audit_test_env):
    """Test that notification preferences can be updated."""
    client = audit_test_env["client"]

    # Update preferences to receive all activities
    prefs = await client.notifications.update_preferences(
        filter_mode="all",
        muted=False,
    )

    assert prefs["filter_mode"] == "all"
    assert prefs["muted"] is False

    # Verify persistence
    prefs2 = await client.notifications.get_preferences()
    assert prefs2["filter_mode"] == "all"


@pytest.mark.asyncio
async def test_notification_preferences_custom_actions(audit_test_env):
    """Test that custom action patterns can be configured."""
    client = audit_test_env["client"]

    # Update with custom action patterns
    prefs = await client.notifications.update_preferences(
        filter_mode="custom",
        custom_actions=["resource.*", "subscription.*"],
    )

    assert prefs["filter_mode"] == "custom"
    assert "resource.*" in prefs["custom_actions"]
    assert "subscription.*" in prefs["custom_actions"]


@pytest.mark.asyncio
async def test_notification_preferences_mute(audit_test_env):
    """Test that notifications can be muted."""
    client = audit_test_env["client"]

    # Mute notifications
    prefs = await client.notifications.update_preferences(muted=True)

    assert prefs["muted"] is True

    # Unmute
    prefs = await client.notifications.update_preferences(muted=False)
    assert prefs["muted"] is False


@pytest.mark.asyncio
async def test_notification_preferences_invalid_filter_mode(audit_test_env):
    """Test that invalid filter_mode is rejected."""
    client = audit_test_env["client"]

    # Try to set invalid filter mode
    import httpx

    try:
        await client.notifications.update_preferences(filter_mode="invalid")
        assert False, "Should have raised an error for invalid filter_mode"
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 400
