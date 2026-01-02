"""
Pytest fixtures for database tests.

Uses SQLite in-memory database for fast, isolated testing without external dependencies.
This matches the embedded Windows deployment model.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import only the models we need for quant tests (avoids outbox NULLS FIRST issue)
from libs.db.models.quant import (
    PipelineDefinition,
    StoreDefinition,
    AccessorDefinition,
    OpDefinition,
    OpMacroDefinition,
    MLModuleDefinition,
    PortfolioOptimizerDefinition,
    PipelineInstance,
    StoreInstance,
    AccessorInstance,
    DatasetInstance,
    SignalSpec,
    ExperimentInstance,
    ModelInstance,
    PortfolioOptimizerInstance,
    BacktestInstance,
    BacktestRun,
    PortfolioOptimizationRun,
    InferenceRun,
    MonitoringRun,
    DatasetLineage,
)
from libs.db.models.resource import Resource, ResourceVersion
from libs.db.models.identity import Tenant, Principal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(scope="function")
def temp_db_path():
    """Create a temporary database file for each test function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_optaic.sqlite"
        yield db_path


@pytest_asyncio.fixture(scope="function")
async def async_engine(temp_db_path):
    """Create async SQLite engine for tests."""
    database_url = f"sqlite+aiosqlite:///{temp_db_path.as_posix()}"

    engine = create_async_engine(
        database_url,
        echo=False,
    )

    # Set SQLite pragmas for better performance and FK support
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create only the tables we need for quant tests
    # This avoids the outbox NULLS FIRST issue
    tables_to_create = [
        Tenant.__table__,
        Principal.__table__,
        Resource.__table__,
        ResourceVersion.__table__,
        # Definition tables
        PipelineDefinition.__table__,
        StoreDefinition.__table__,
        AccessorDefinition.__table__,
        OpDefinition.__table__,
        OpMacroDefinition.__table__,
        MLModuleDefinition.__table__,
        PortfolioOptimizerDefinition.__table__,
        # Instance tables
        PipelineInstance.__table__,
        StoreInstance.__table__,
        AccessorInstance.__table__,
        DatasetInstance.__table__,
        SignalSpec.__table__,
        ExperimentInstance.__table__,
        ModelInstance.__table__,
        PortfolioOptimizerInstance.__table__,
        BacktestInstance.__table__,
        # Run tables
        BacktestRun.__table__,
        PortfolioOptimizationRun.__table__,
        InferenceRun.__table__,
        MonitoringRun.__table__,
        # Lineage
        DatasetLineage.__table__,
    ]

    async with engine.begin() as conn:
        for table in tables_to_create:
            await conn.run_sync(table.create, checkfirst=True)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_engine) -> AsyncSession:
    """Create async database session for tests.

    Each test gets a fresh transaction that is rolled back after the test.
    """
    async_session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with async_session_factory() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def test_tenant(db_session: AsyncSession):
    """Create a test tenant and return its ID."""
    tenant_id = uuid.uuid4()

    await db_session.execute(
        text("""
            INSERT INTO tenants (id, name, created_at)
            VALUES (:id, :name, :created_at)
        """),
        {"id": str(tenant_id), "name": "Test Tenant", "created_at": utcnow()},
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
            "created_at": utcnow(),
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
            "created_at": utcnow(),
            "updated_at": utcnow(),
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
            "created_at": utcnow(),
        },
    )
    await db_session.flush()

    yield version_id
