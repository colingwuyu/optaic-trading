"""Debug script to isolate test failure.

Run this to understand why test_admin_create_team_space fails after list_definitions.

Usage:
    1. Start "API: E2E Debug Server" in VS Code
    2. Run: python tests/e2e/debug_test_isolation.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libs.sdk_py import (
    AsyncPlatformClient,
    SYSTEM_PRINCIPAL_ID,
    SYSTEM_TENANT_ID,
)


async def test_list_then_create():
    """Reproduce the issue: list_definitions then create_user."""
    api_url = "http://127.0.0.1:8082"

    client = AsyncPlatformClient(
        base_url=api_url,
        principal_id=str(SYSTEM_PRINCIPAL_ID),
        tenant_id=str(SYSTEM_TENANT_ID),
        timeout=60.0,
    )

    try:
        # First: check server is running
        print("[1] Checking health...")
        health = await client.health.get()
        print(f"    Health: {health}")

        # Second: list definitions (this is what test_list_pipeline_definitions_includes_system does)
        print("[2] Listing pipeline definitions...")
        definitions = await client.pipelines.list_definitions()
        print(f"    Found {len(definitions)} definitions")
        for d in definitions[:3]:
            print(f"      - {d.get('name')}: {d.get('code_ref')}")

        # Third: try to create user (this is what test_admin_create_team_space does first)
        print("[3] Creating user with space...")
        try:
            result = await client.admin.create_user_with_space(
                display_name="Debug Test User",
                email="debug-test@example.com",
            )
            print(f"    Created user: {result}")
        except Exception as e:
            print(f"    ERROR creating user: {type(e).__name__}: {e}")
            raise

    finally:
        await client.close()


async def test_create_only():
    """Test just creating a user (no list_definitions first)."""
    api_url = "http://127.0.0.1:8082"

    client = AsyncPlatformClient(
        base_url=api_url,
        principal_id=str(SYSTEM_PRINCIPAL_ID),
        tenant_id=str(SYSTEM_TENANT_ID),
        timeout=60.0,
    )

    try:
        print("[1] Checking health...")
        health = await client.health.get()
        print(f"    Health: {health}")

        print("[2] Creating user with space (no list_definitions first)...")
        try:
            result = await client.admin.create_user_with_space(
                display_name="Debug Test User 2",
                email="debug-test-2@example.com",
            )
            print(f"    Created user: {result}")
        except Exception as e:
            print(f"    ERROR creating user: {type(e).__name__}: {e}")
            raise

    finally:
        await client.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Debug Test: Isolation Issue")
    print("=" * 60)

    # First, test create without list_definitions
    print("\n--- Test 1: Create user WITHOUT list_definitions first ---")
    try:
        asyncio.run(test_create_only())
        print("SUCCESS: User creation works alone")
    except Exception as e:
        print(f"FAILED: {e}")

    print("\n--- Test 2: List definitions THEN create user ---")
    try:
        asyncio.run(test_list_then_create())
        print("SUCCESS: User creation works after list_definitions")
    except Exception as e:
        print(f"FAILED: {e}")
        print("\nThis confirms the issue is related to list_definitions")
