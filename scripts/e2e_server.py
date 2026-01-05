"""E2E Test Server Launcher.

Starts the full OptAIC stack for E2E testing:
- Database migrations
- Centrifugo (WebSocket)
- Redis (optional, for caching)
- API server
- Worker (outbox consumer)
- Agent (LLM processor)

Usage:
    python scripts/e2e_server.py

Or via VS Code "API: E2E Debug Server (Full Stack)" launch config.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set E2E environment before importing anything else
E2E_DATA_DIR = PROJECT_ROOT / ".tmp" / "optaic-e2e-data"
E2E_DB_PATH = E2E_DATA_DIR / "db" / "optaic.sqlite"
E2E_DB_URL = f"sqlite+aiosqlite:///{E2E_DB_PATH}"

os.environ.setdefault("OPTAIC_DATA_DIR", str(E2E_DATA_DIR))
os.environ.setdefault("DATABASE_URL", E2E_DB_URL)
os.environ.setdefault("MODE", "embedded")
os.environ.setdefault("API_HOST", "127.0.0.1")
os.environ.setdefault("API_PORT", "8082")
os.environ.setdefault("CENTRIFUGO_PORT", "8002")
os.environ.setdefault("CENTRIFUGO_API_KEY", "e2e-test-api-key")
os.environ.setdefault("CENTRIFUGO_TOKEN_SECRET", "e2e-test-secret")
os.environ.setdefault("CENTRIFUGO_HMAC_SECRET", "e2e-test-secret")


def main() -> int:
    """Run the full E2E server stack."""
    from optaic.config import Settings
    from optaic.runtime.runtime_config import RuntimeConfig, PrefectConfig, MlflowConfig
    from optaic.runtime.supervisor import SupervisorConfig, run_supervisor

    # Ensure data directories exist
    E2E_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (E2E_DATA_DIR / "db").mkdir(parents=True, exist_ok=True)
    (E2E_DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (E2E_DATA_DIR / "state").mkdir(parents=True, exist_ok=True)

    settings = Settings()

    # Create runtime config with E2E defaults (engines disabled)
    prefect_config = PrefectConfig(enabled=False)
    mlflow_config = MlflowConfig(enabled=False)
    runtime_config = RuntimeConfig(
        data_dir=E2E_DATA_DIR,
        prefect=prefect_config,
        mlflow=mlflow_config,
    )

    # Configure for E2E testing
    config = SupervisorConfig(
        data_dir=E2E_DATA_DIR,
        settings=settings,
        host=settings.api_host,
        port=settings.api_port,
        database_url=E2E_DB_URL,
        start_worker=True,
        start_agent=True,
        open_browser=False,
        with_redis=False,  # Redis optional for E2E
        redis_url=None,
        redis_port=6379,
        redis_bind="127.0.0.1",
        redis_version="7.4.1",
        redis_flavor="msys2",
        prefect=runtime_config.prefect,
        mlflow=runtime_config.mlflow,
    )

    print("=" * 60)
    print("OptAIC E2E Test Server")
    print("=" * 60)
    print(f"Data directory: {E2E_DATA_DIR}")
    print(f"Database: {E2E_DB_PATH}")
    print(f"API: http://{settings.api_host}:{settings.api_port}")
    print(f"Centrifugo: http://127.0.0.1:{settings.centrifugo_port}")
    print("=" * 60)

    return run_supervisor(config)


if __name__ == "__main__":
    sys.exit(main())
