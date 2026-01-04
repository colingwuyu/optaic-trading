"""
Pytest fixtures for database tests.

Database fixtures (db_session, test_engine) are provided by the root conftest.py
which uses the sandbox infrastructure. This file provides additional fixtures
specific to database model testing.
"""

import uuid
from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def utcnow_iso() -> str:
    """Return current UTC time as ISO format string.

    Uses ISO format to avoid Python 3.12+ deprecation warning about
    the default sqlite3 datetime adapter.
    """
    return datetime.now(timezone.utc).isoformat()


@pytest_asyncio.fixture(scope="function")
async def test_tenant(db_session: AsyncSession):
    """Create a test tenant and return its ID."""
    tenant_id = uuid.uuid4()

    await db_session.execute(
        text("""
            INSERT INTO tenants (id, name, created_at)
            VALUES (:id, :name, :created_at)
        """),
        {"id": str(tenant_id), "name": "Test Tenant", "created_at": utcnow_iso()},
    )
    await db_session.flush()

    yield tenant_id


@pytest_asyncio.fixture(scope="function")
async def test_principal(db_session: AsyncSession, test_tenant):
    """Create a test principal and return its ID."""
    principal_id = uuid.uuid4()

    await db_session.execute(
        text("""
            INSERT INTO principals (id, tenant_id, kind, status, display_name, created_at)
            VALUES (:id, :tenant_id, :kind, :status, :display_name, :created_at)
        """),
        {
            "id": str(principal_id),
            "tenant_id": str(test_tenant),
            "kind": "user",
            "status": "active",
            "display_name": "Test User",
            "created_at": utcnow_iso(),
        },
    )
    await db_session.flush()

    yield principal_id


@pytest_asyncio.fixture(scope="function")
async def test_resource(db_session: AsyncSession, test_tenant, test_principal):
    """Create a test resource and return its ID."""
    resource_id = uuid.uuid4()

    await db_session.execute(
        text("""
            INSERT INTO resources (id, tenant_id, owner_principal_id, type, name, status, metadata, created_at, updated_at)
            VALUES (:id, :tenant_id, :owner_principal_id, :type, :name, :status, :metadata, :created_at, :updated_at)
        """),
        {
            "id": str(resource_id),
            "tenant_id": str(test_tenant),
            "owner_principal_id": str(test_principal),
            "type": "Space",
            "name": "Test Resource",
            "status": "active",
            "metadata": "{}",
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
        },
    )
    await db_session.flush()

    yield resource_id


@pytest_asyncio.fixture(scope="function")
async def test_resource_version(
    db_session: AsyncSession, test_resource, test_tenant, test_principal
):
    """Create a test resource version and return its ID."""
    version_id = uuid.uuid4()

    await db_session.execute(
        text("""
            INSERT INTO resource_versions (id, tenant_id, resource_id, created_by, created_at)
            VALUES (:id, :tenant_id, :resource_id, :created_by, :created_at)
        """),
        {
            "id": str(version_id),
            "tenant_id": str(test_tenant),
            "resource_id": str(test_resource),
            "created_by": str(test_principal),
            "created_at": utcnow_iso(),
        },
    )
    await db_session.flush()

    yield version_id
