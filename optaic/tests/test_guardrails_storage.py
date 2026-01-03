"""Tests for guardrails storage layer.

Tests:
- test_upsert_and_get_active_bundle
- test_replacing_bundle_deactivates_previous
- test_insert_and_list_reports
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from optaic.guardrails import (
    ContractBundle,
    ContractInstance,
    ContractRef,
    ValidationIssue,
    ValidationReport,
    contract_hash,
)
from optaic.guardrails.storage import ContractBundleStore, ValidationReportStore


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def async_db():
    """Create an in-memory SQLite database for testing."""
    # Create async engine
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            CREATE TABLE resource_contract_bundles (
                bundle_id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                resource_version_id TEXT,
                created_by TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                bundle_json TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE validation_reports (
                report_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                target_id TEXT NOT NULL,
                ok BOOLEAN NOT NULL,
                enforced_as TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                correlation_id TEXT,
                report_json TEXT NOT NULL
            )
        """)
        )

    # Create session
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()


def _make_bundle(resource_id: str, bundle_id: str | None = None) -> ContractBundle:
    """Create a test ContractBundle."""
    ref = ContractRef(
        contract_kind="test",
        contract_name="test_contract",
        version="1.0.0",
    )
    instance = ContractInstance(
        ref=ref,
        config_json="{}",
        contract_hash=contract_hash(ref, "{}"),
    )
    return ContractBundle(
        bundle_id=bundle_id or str(uuid4()),
        resource_id=resource_id,
        created_by="test_user",
        created_at=datetime.now(timezone.utc),
        contracts=[instance],
    )


def _make_report(
    target_id: str,
    scope: str = "resource",
    ok: bool = True,
    report_id: str | None = None,
) -> ValidationReport:
    """Create a test ValidationReport."""
    return ValidationReport(
        report_id=report_id or str(uuid4()),
        scope=scope,
        target_id=target_id,
        ok=ok,
        enforced_as="warn",
        issues=[],
        contract_hashes=[],
        created_by="test_user",
        created_at=datetime.now(timezone.utc),
    )


# =============================================================================
# ContractBundleStore Tests
# =============================================================================


@pytest.mark.asyncio
async def test_upsert_and_get_active_bundle(async_db: AsyncSession) -> None:
    """Test inserting and retrieving an active bundle."""
    resource_id = "resource-123"
    bundle = _make_bundle(resource_id)

    # Insert bundle
    await ContractBundleStore.upsert_active_bundle(async_db, bundle)
    await async_db.commit()

    # Retrieve it
    retrieved = await ContractBundleStore.get_active_bundle(async_db, resource_id)

    assert retrieved is not None
    assert retrieved.bundle_id == bundle.bundle_id
    assert retrieved.resource_id == resource_id
    assert len(retrieved.contracts) == 1
    assert retrieved.contracts[0].ref.contract_name == "test_contract"


@pytest.mark.asyncio
async def test_get_active_bundle_not_found(async_db: AsyncSession) -> None:
    """Test retrieving a bundle that doesn't exist."""
    result = await ContractBundleStore.get_active_bundle(async_db, "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_replacing_bundle_deactivates_previous(async_db: AsyncSession) -> None:
    """Test that upserting a new bundle deactivates the previous one."""
    resource_id = "resource-456"

    # Insert first bundle
    bundle1 = _make_bundle(resource_id, bundle_id="bundle-1")
    await ContractBundleStore.upsert_active_bundle(async_db, bundle1)
    await async_db.commit()

    # Verify it's active
    active = await ContractBundleStore.get_active_bundle(async_db, resource_id)
    assert active is not None
    assert active.bundle_id == "bundle-1"

    # Insert second bundle (should deactivate first)
    bundle2 = _make_bundle(resource_id, bundle_id="bundle-2")
    await ContractBundleStore.upsert_active_bundle(async_db, bundle2)
    await async_db.commit()

    # Verify new bundle is active
    active = await ContractBundleStore.get_active_bundle(async_db, resource_id)
    assert active is not None
    assert active.bundle_id == "bundle-2"

    # Verify there's only one active bundle
    from sqlalchemy import text

    result = await async_db.execute(
        text(
            "SELECT COUNT(*) FROM resource_contract_bundles WHERE resource_id = :rid AND is_active = 1"
        ),
        {"rid": resource_id},
    )
    count = result.scalar()
    assert count == 1


# =============================================================================
# ValidationReportStore Tests
# =============================================================================


@pytest.mark.asyncio
async def test_insert_and_list_reports(async_db: AsyncSession) -> None:
    """Test inserting and listing reports."""
    target_id = "target-789"

    # Insert multiple reports
    report1 = _make_report(target_id, scope="resource", ok=True)
    report2 = _make_report(target_id, scope="resource", ok=False)
    report3 = _make_report("other-target", scope="run", ok=True)

    await ValidationReportStore.insert_report(async_db, report1)
    await ValidationReportStore.insert_report(async_db, report2)
    await ValidationReportStore.insert_report(async_db, report3)
    await async_db.commit()

    # List all reports
    all_reports = await ValidationReportStore.list_reports(async_db)
    assert len(all_reports) == 3

    # Filter by scope
    resource_reports = await ValidationReportStore.list_reports(
        async_db, scope="resource"
    )
    assert len(resource_reports) == 2

    # Filter by target_id
    target_reports = await ValidationReportStore.list_reports(
        async_db, target_id=target_id
    )
    assert len(target_reports) == 2

    # Filter by both
    filtered = await ValidationReportStore.list_reports(
        async_db, scope="resource", target_id=target_id
    )
    assert len(filtered) == 2


@pytest.mark.asyncio
async def test_list_reports_respects_limit(async_db: AsyncSession) -> None:
    """Test that list_reports respects the limit parameter."""
    target_id = "target-limit"

    # Insert 5 reports
    for i in range(5):
        report = _make_report(target_id, report_id=f"report-{i}")
        await ValidationReportStore.insert_report(async_db, report)
    await async_db.commit()

    # List with limit
    reports = await ValidationReportStore.list_reports(
        async_db, target_id=target_id, limit=3
    )
    assert len(reports) == 3


@pytest.mark.asyncio
async def test_report_roundtrip_preserves_data(async_db: AsyncSession) -> None:
    """Test that report data is preserved through storage roundtrip."""
    report = ValidationReport(
        report_id="report-roundtrip",
        scope="promotion",
        target_id="target-rt",
        ok=False,
        enforced_as="block",
        issues=[
            ValidationIssue(
                severity="error",
                code="TEST_ERROR",
                message="Test error message",
                path="$.field",
                meta={"key": "value"},
            )
        ],
        contract_hashes=["hash1", "hash2"],
        created_by="test_user",
        created_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        correlation_id="corr-123",
    )

    await ValidationReportStore.insert_report(async_db, report)
    await async_db.commit()

    reports = await ValidationReportStore.list_reports(async_db, target_id="target-rt")
    assert len(reports) == 1

    retrieved = reports[0]
    assert retrieved.report_id == "report-roundtrip"
    assert retrieved.scope == "promotion"
    assert retrieved.ok is False
    assert retrieved.enforced_as == "block"
    assert len(retrieved.issues) == 1
    assert retrieved.issues[0].code == "TEST_ERROR"
    assert retrieved.issues[0].meta == {"key": "value"}
    assert retrieved.contract_hashes == ["hash1", "hash2"]
    assert retrieved.correlation_id == "corr-123"
