"""
Root pytest configuration - Sandbox-based testing infrastructure.

ALL tests run against real infrastructure by default:
- SQLite database (persistent during session)
- Prefect server (real deployment_id, flow_run_id, task_run_id)
- MLflow server (real experiment_id, run_id, metrics)
- Centrifugo server (real WebSocket publishing)

The sandbox starts automatically when pytest runs and provides:
- Consistent test environment across dev and CI/CD
- Real infrastructure validation (not mocks)
- Persistent data directory for debugging

Usage:
    pytest                           # Runs all tests against sandbox
    pytest libs/db/tests/            # Specific tests
    OPTAIC_TEST_SANDBOX_DIR=/custom/path pytest  # Custom sandbox location
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Generator, Optional

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, Pool

# =============================================================================
# SANDBOX CONFIGURATION
# =============================================================================

# Use session-scoped temp directory for test isolation
# This ensures each pytest session gets a clean sandbox
_SESSION_TEMP_DIR: Optional[Path] = None


def _get_session_data_dir() -> Path:
    """Get the session-scoped data directory for sandbox."""
    global _SESSION_TEMP_DIR
    if _SESSION_TEMP_DIR is None:
        _SESSION_TEMP_DIR = Path(tempfile.mkdtemp(prefix="optaic_sandbox_"))
    return _SESSION_TEMP_DIR


# Infrastructure server ports (use high ports to avoid conflicts)
PREFECT_PORT = 14200
MLFLOW_PORT = 14500
CENTRIFUGO_PORT = 14000
# Port for E2E test server - matches .vscode/.env.e2e configuration
# Can be overridden via E2E_API_PORT environment variable
API_SERVER_PORT = int(os.environ.get("E2E_API_PORT", "8082"))

# Server processes (managed at session scope)
_server_processes: dict[str, subprocess.Popen] = {}


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================


def pytest_configure(config):
    """Configure pytest before test collection."""
    # Register custom markers
    config.addinivalue_line("markers", "integration: marks tests as integration tests")

    # Set up environment for test database
    data_dir = _get_session_data_dir()
    db_path = data_dir / "test_optaic.sqlite"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    os.environ["DATABASE_URL"] = db_url

    # Set Prefect API URL for orchestration tests
    os.environ["PREFECT_API_URL"] = f"http://127.0.0.1:{PREFECT_PORT}/api"

    # Disable Prefect's API logging to avoid "Error logging to API" on shutdown
    # This prevents the background log worker from trying to send logs to a dead server
    os.environ["PREFECT_LOGGING_TO_API_ENABLED"] = "false"

    # Set MLflow tracking URI
    os.environ["MLFLOW_TRACKING_URI"] = f"http://127.0.0.1:{MLFLOW_PORT}"

    # Set Redis URL (dummy for tests that don't need Redis)
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

    # Clear settings cache so it picks up our test environment
    try:
        from libs.core.settings import get_settings

        get_settings.cache_clear()
    except ImportError:
        pass


def pytest_unconfigure(config):
    """Clean up after all tests complete."""
    global _SESSION_TEMP_DIR

    # Stop all server processes
    for name, proc in _server_processes.items():
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    _server_processes.clear()

    # Clean up temp directory
    if _SESSION_TEMP_DIR and _SESSION_TEMP_DIR.exists():
        import shutil

        try:
            shutil.rmtree(_SESSION_TEMP_DIR, ignore_errors=True)
        except Exception:
            pass


# =============================================================================
# SQLITE PRAGMAS
# =============================================================================


@event.listens_for(Pool, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    """Configure SQLite for optimal test performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=OFF")  # Allow cascade-free testing
    cursor.close()


# =============================================================================
# DATABASE FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a shared async engine for all tests.

    Session-scoped to avoid recreating the engine for every test.
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
        async with session.begin():
            yield session
            # Rollback is automatic when exiting the context manager


@pytest.fixture(scope="session", autouse=True)
def patch_async_session_local(test_engine):
    """Patch AsyncSessionLocal to use the test engine.

    This allows code that imports AsyncSessionLocal directly to use the test database.
    """
    try:
        from libs.db import session as session_module

        original_factory = session_module.AsyncSessionLocal

        test_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        session_module.AsyncSessionLocal = test_factory

        yield

        session_module.AsyncSessionLocal = original_factory
    except ImportError:
        yield


# =============================================================================
# INFRASTRUCTURE SERVER FIXTURES
# =============================================================================


def _wait_for_server(url: str, timeout: int = 60) -> bool:
    """Wait for a server to become healthy."""
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 400:
                    return True
        except (urllib.error.URLError, Exception):
            pass
        time.sleep(0.5)
    return False


def _create_default_work_pool(api_url: str) -> None:
    """Create a default work pool for Prefect tests."""
    import asyncio

    async def _create_pool():
        try:
            from prefect.client.orchestration import get_client

            os.environ["PREFECT_API_URL"] = api_url
            async with get_client() as client:
                # Check if work pool already exists
                try:
                    await client.read_work_pool("default")
                    return  # Already exists
                except Exception:
                    pass

                # Create default work pool (process type for local execution)
                await client.create_work_pool(
                    work_pool={"name": "default", "type": "process"},
                )
        except Exception as e:
            # Non-fatal - some tests may not need work pools
            import logging

            logging.getLogger(__name__).warning(f"Could not create work pool: {e}")

    asyncio.run(_create_pool())


@pytest.fixture(scope="session")
def prefect_server() -> Generator[str, None, None]:
    """Start Prefect server for the test session.

    Returns the Prefect API URL.
    """
    api_url = f"http://127.0.0.1:{PREFECT_PORT}/api"

    # Check if already running
    if _wait_for_server(api_url.replace("/api", "/api/health"), timeout=2):
        _create_default_work_pool(api_url)
        yield api_url
        return

    # Start Prefect server
    data_dir = _get_session_data_dir() / "prefect"
    data_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PREFECT_HOME"] = str(data_dir)
    env["PREFECT_SERVER_DATABASE_CONNECTION_URL"] = (
        f"sqlite+aiosqlite:///{data_dir / 'prefect.db'}"
    )

    cmd = [
        sys.executable,
        "-m",
        "prefect",
        "server",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        str(PREFECT_PORT),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )
    _server_processes["prefect"] = proc

    # Wait for server to be ready
    if not _wait_for_server(api_url.replace("/api", "/api/health"), timeout=60):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"Prefect server did not start at {api_url}")

    # Create default work pool
    _create_default_work_pool(api_url)

    yield api_url


@pytest.fixture(scope="session")
def mlflow_server() -> Generator[str, None, None]:
    """Start MLflow server for the test session.

    Returns the MLflow tracking URI.
    """
    tracking_uri = f"http://127.0.0.1:{MLFLOW_PORT}"

    # Check if already running
    if _wait_for_server(tracking_uri, timeout=2):
        yield tracking_uri
        return

    # Start MLflow server
    data_dir = _get_session_data_dir() / "mlflow"
    backend_dir = data_dir / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = data_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    backend_uri = f"sqlite:///{backend_dir / 'mlflow.db'}"
    artifact_uri = artifact_dir.as_uri()

    cmd = [
        sys.executable,
        "-m",
        "mlflow",
        "server",
        "--host",
        "127.0.0.1",
        "--port",
        str(MLFLOW_PORT),
        "--backend-store-uri",
        backend_uri,
        "--default-artifact-root",
        artifact_uri,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _server_processes["mlflow"] = proc

    # Wait for server to be ready
    if not _wait_for_server(tracking_uri, timeout=60):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"MLflow server did not start at {tracking_uri}")

    yield tracking_uri


@pytest.fixture(scope="session")
def centrifugo_server() -> Generator[dict, None, None]:
    """Start Centrifugo server for the test session.

    Uses OptAIC's CentrifugoManager which automatically downloads the binary if needed.
    Returns a dict with http_url, ws_url, api_key, and token_secret.
    """
    from optaic.runtime.centrifugo_manager import (
        CentrifugoConfig,
        CentrifugoManager,
        DEFAULT_CENTRIFUGO_VERSION,
    )

    api_key = "test-api-key-32-characters-long!"
    token_secret = "test-token-secret-32-chars-long!"
    http_url = f"http://127.0.0.1:{CENTRIFUGO_PORT}"

    # Check if already running
    if _wait_for_server(http_url, timeout=2):
        yield {
            "http_url": http_url,
            "ws_url": f"ws://127.0.0.1:{CENTRIFUGO_PORT}/connection/websocket",
            "api_key": api_key,
            "token_secret": token_secret,
        }
        return

    # Use OptAIC's CentrifugoManager (auto-downloads binary if needed)
    data_dir = _get_session_data_dir()
    config = CentrifugoConfig(
        data_dir=data_dir,
        port=CENTRIFUGO_PORT,
        api_key=api_key,
        token_secret=token_secret,
        allowed_origins=["*"],
    )

    manager = CentrifugoManager(config, DEFAULT_CENTRIFUGO_VERSION)
    proc = manager.start(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        wait=False,  # We'll wait manually for more control
    )
    _server_processes["centrifugo"] = proc

    # Wait for server to be ready (Centrifugo health endpoint is /health)
    health_url = f"{http_url}/health"
    if not _wait_for_server(health_url, timeout=30):
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"Centrifugo server did not start at {http_url}")

    yield {
        "http_url": http_url,
        "ws_url": f"ws://127.0.0.1:{CENTRIFUGO_PORT}/connection/websocket",
        "api_key": api_key,
        "token_secret": token_secret,
    }


# =============================================================================
# ENVIRONMENT FIXTURES (set env vars for tests)
# =============================================================================


@pytest.fixture
def prefect_env(prefect_server: str) -> Generator[str, None, None]:
    """Set PREFECT_API_URL environment variable for tests."""
    old_value = os.environ.get("PREFECT_API_URL")
    os.environ["PREFECT_API_URL"] = prefect_server
    yield prefect_server
    if old_value is not None:
        os.environ["PREFECT_API_URL"] = old_value
    else:
        os.environ.pop("PREFECT_API_URL", None)


@pytest.fixture
def mlflow_env(mlflow_server: str) -> Generator[str, None, None]:
    """Set MLFLOW_TRACKING_URI environment variable for tests."""
    import mlflow

    old_value = os.environ.get("MLFLOW_TRACKING_URI")
    os.environ["MLFLOW_TRACKING_URI"] = mlflow_server
    mlflow.set_tracking_uri(mlflow_server)
    yield mlflow_server
    if old_value is not None:
        os.environ["MLFLOW_TRACKING_URI"] = old_value
    else:
        os.environ.pop("MLFLOW_TRACKING_URI", None)


# =============================================================================
# SESSION SETUP
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_test_session(test_engine):
    """Setup test session - ensure database is ready."""
    yield

    # Cleanup handled by pytest_unconfigure


# =============================================================================
# API SERVER FIXTURE (for live E2E tests)
# =============================================================================


def _ensure_schema_in_subprocess_db(db_url: str) -> None:
    """Create database schema in a subprocess-compatible way.

    The test_engine fixture creates schema with a patched AsyncSessionLocal,
    but the subprocess uses its own engine. We need to ensure the schema
    exists in the database file the subprocess will use.
    """
    from sqlalchemy import create_engine
    from libs.db.base import Base
    import libs.db.models  # noqa: F401 - Register models

    # Convert async URL to sync for schema creation
    sync_url = db_url.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url, echo=False)

    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()


@pytest.fixture(scope="session")
def api_server() -> Generator[str, None, None]:
    """Start the API server for live E2E tests.

    This runs uvicorn with the FastAPI app, which:
    1. Runs lifespan startup hooks (bootstrap, seeding)
    2. Serves the full API on a test port
    3. Allows SDK clients to connect via HTTP

    Uses a SEPARATE database from in-process tests to ensure isolation.
    This prevents state leaking between test types.

    Returns the API base URL.
    """
    api_url = f"http://127.0.0.1:{API_SERVER_PORT}"
    health_url = f"{api_url}/healthz"

    # Check if already running (e.g., "API: E2E Debug Server" from VS Code)
    if _wait_for_server(health_url, timeout=2):
        print(f"[api_server] Using existing server at {api_url}")
        yield api_url
        return

    # Create a SEPARATE database for the live server tests
    # This ensures isolation from in-process tests
    live_db_dir = tempfile.mkdtemp(prefix="optaic_live_server_")
    live_db_path = os.path.join(live_db_dir, "live_test.sqlite")
    db_url = f"sqlite+aiosqlite:///{live_db_path}"
    print(f"[api_server] Starting API with isolated DATABASE_URL={db_url}")

    # Ensure schema exists in the database file (not patched)
    # The subprocess uses its own engine, so we create schema directly
    _ensure_schema_in_subprocess_db(db_url)

    env = os.environ.copy()
    env["DATABASE_URL"] = db_url

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(API_SERVER_PORT),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )
    _server_processes["api"] = proc

    # Wait for server to be ready (give more time for lifespan)
    if not _wait_for_server(health_url, timeout=60):
        # Read any output for debugging
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=5)
            print(f"API server output:\n{out}")
        except Exception:
            proc.kill()
        pytest.fail(f"API server did not start at {api_url}")

    # Give a moment for lifespan to complete after healthz is available
    time.sleep(2)

    # Print first part of server output for debugging

    if sys.platform != "win32":
        # Use select for non-blocking read on Unix
        import select as sel

        if sel.select([proc.stdout], [], [], 0)[0]:
            lines = proc.stdout.read(2000)
            print(f"[api_server] Server output:\n{lines}")

    yield api_url

    # On cleanup, capture any remaining output
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
        if out:
            print(f"[api_server] Final output:\n{out[:2000]}")
    except Exception:
        proc.kill()


@pytest_asyncio.fixture(scope="function")
async def sdk_live_client(api_server: str):
    """Create an SDK client connected to the live API server.

    This fixture provides a real HTTP connection to the API server,
    allowing tests to verify startup hooks (bootstrap, seeding) work.

    Uses a longer timeout (60s) for complex operations like creating
    users with spaces which involve multiple DB operations.
    """
    from libs.sdk_py import AsyncPlatformClient, SYSTEM_PRINCIPAL_ID, SYSTEM_TENANT_ID

    client = AsyncPlatformClient(
        base_url=api_server,
        principal_id=str(SYSTEM_PRINCIPAL_ID),
        tenant_id=str(SYSTEM_TENANT_ID),
        timeout=60.0,  # Longer timeout for complex operations
    )
    yield client
    await client.close()
