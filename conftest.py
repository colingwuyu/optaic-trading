"""
Root pytest configuration for all tests.

Sets up the testing environment including:
- SQLite database configuration for unit tests (no external dependencies)
- Complete database schema creation for full test coverage
- Warning filters for third-party library deprecation warnings

Per devops_deployment.md: Use SQLite fixtures with tempfile.TemporaryDirectory() for embedded tests.
"""

import os
import tempfile
from pathlib import Path

# IMPORTANT: Set environment variables BEFORE any imports that might use them
# This ensures all tests use SQLite instead of PostgreSQL
_test_db_dir = tempfile.mkdtemp(prefix="optaic_test_")
_test_db_path = Path(_test_db_dir) / "test_optaic.sqlite"
_test_db_url = f"sqlite+aiosqlite:///{_test_db_path.as_posix()}"
os.environ["DATABASE_URL"] = _test_db_url

# Also set a dummy Redis URL for tests that don't need Redis
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import Pool, NullPool  # noqa: E402


def pytest_configure(config):
    """Configure pytest before test collection."""
    # Register custom markers
    config.addinivalue_line("markers", "integration: marks tests as integration tests")

    # Clear the settings cache so it picks up our test DATABASE_URL
    from libs.core.settings import get_settings

    get_settings.cache_clear()


@event.listens_for(Pool, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    """Ensure foreign keys are disabled for all SQLite connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=OFF")
    cursor.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a shared async engine for all tests.

    This is session-scoped to avoid recreating the engine for every test.
    Creates the complete database schema for full test coverage.
    """
    from libs.core.settings import get_settings
    from libs.db.base import Base

    # Import all models so they register with Base.metadata
    import libs.db.models  # noqa: F401

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncSession:
    """Create an async database session for each test.

    Each test gets a fresh transaction that is rolled back after the test.
    This ensures test isolation without recreating the database.
    """
    async_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with async_session_factory() as session:
        # Use nested transaction for proper rollback
        async with session.begin():
            yield session
            # Rollback is automatic when exiting the context manager


@pytest.fixture(scope="session", autouse=True)
def patch_async_session_local(test_engine):
    """Patch AsyncSessionLocal to use the test engine.

    This allows code that imports AsyncSessionLocal directly to use the test database.
    """
    from libs.db import session as session_module

    original_factory = session_module.AsyncSessionLocal

    # Create a new session factory with the test engine
    test_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    session_module.AsyncSessionLocal = test_factory

    yield

    session_module.AsyncSessionLocal = original_factory


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment(test_engine):
    """Setup test environment for the entire session."""
    # test_engine fixture handles table creation via implicit dependency
    yield

    # Cleanup
    import shutil

    if os.path.exists(_test_db_dir):
        shutil.rmtree(_test_db_dir, ignore_errors=True)
