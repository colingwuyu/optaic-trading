"""Persistent Test Sandbox Infrastructure.

This module manages a persistent test sandbox that runs OptAIC's full infrastructure:
- API server (FastAPI + Uvicorn)
- Worker (outbox consumer)
- Centrifugo (real-time WebSocket)
- Prefect (workflow orchestration)
- MLflow (experiment tracking)
- SQLite or PostgreSQL database

The sandbox is NOT recreated for each test run. Instead, it:
1. Checks if the sandbox is already running
2. If not, starts all infrastructure services
3. Checks for database migrations and applies if needed
4. Checks for package upgrades if requested
5. Returns connection info for tests

Usage:
    from tests.integration.sandbox import get_sandbox, SandboxConfig

    # Get or create sandbox
    sandbox = get_sandbox()

    # Run tests against sandbox endpoints
    api_url = sandbox.api_url
    prefect_url = sandbox.prefect_api_url
    mlflow_url = sandbox.mlflow_tracking_uri
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Default sandbox directory under user's local app data
DEFAULT_SANDBOX_DIR = Path(
    os.environ.get("OPTAIC_TEST_SANDBOX_DIR", Path.home() / ".optaic-test-sandbox")
)


@dataclass
class SandboxConfig:
    """Configuration for the test sandbox."""

    data_dir: Path = field(default_factory=lambda: DEFAULT_SANDBOX_DIR)
    api_port: int = 19080
    centrifugo_port: int = 19000
    prefect_port: int = 19200
    mlflow_port: int = 19500
    with_prefect: bool = True
    with_mlflow: bool = True
    with_worker: bool = True
    with_agent: bool = False
    auto_upgrade: bool = True
    database_url: Optional[str] = None

    def __post_init__(self):
        if self.database_url is None:
            db_path = self.data_dir / "test.db"
            self.database_url = f"sqlite:///{db_path.as_posix()}"

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def prefect_api_url(self) -> str:
        return f"http://127.0.0.1:{self.prefect_port}/api"

    @property
    def mlflow_tracking_uri(self) -> str:
        return f"http://127.0.0.1:{self.mlflow_port}"

    @property
    def centrifugo_url(self) -> str:
        return f"http://127.0.0.1:{self.centrifugo_port}"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state" / "sandbox_state.json"


@dataclass
class SandboxState:
    """Runtime state of the test sandbox."""

    running: bool = False
    pid: Optional[int] = None
    api_url: Optional[str] = None
    prefect_api_url: Optional[str] = None
    mlflow_tracking_uri: Optional[str] = None
    centrifugo_url: Optional[str] = None
    started_at: Optional[str] = None
    version: Optional[str] = None
    db_revision: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "pid": self.pid,
            "api_url": self.api_url,
            "prefect_api_url": self.prefect_api_url,
            "mlflow_tracking_uri": self.mlflow_tracking_uri,
            "centrifugo_url": self.centrifugo_url,
            "started_at": self.started_at,
            "version": self.version,
            "db_revision": self.db_revision,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SandboxState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SandboxManager:
    """Manages a persistent test sandbox environment.

    The sandbox runs the full OptAIC stack and persists between test runs.
    """

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self._state: Optional[SandboxState] = None
        self._process: Optional[subprocess.Popen] = None

    @property
    def state(self) -> SandboxState:
        """Get current sandbox state, loading from disk if needed."""
        if self._state is None:
            self._state = self._load_state()
        return self._state

    @property
    def api_url(self) -> str:
        return self.config.api_url

    @property
    def prefect_api_url(self) -> str:
        return self.config.prefect_api_url

    @property
    def mlflow_tracking_uri(self) -> str:
        return self.config.mlflow_tracking_uri

    @property
    def centrifugo_url(self) -> str:
        return self.config.centrifugo_url

    def ensure_running(self) -> "SandboxManager":
        """Ensure the sandbox is running, starting if needed.

        This method:
        1. Checks if sandbox is already running
        2. If not, starts all infrastructure
        3. Checks/applies database migrations
        4. Returns self for chaining
        """
        if self.is_running():
            print(f"[sandbox] Already running at {self.config.api_url}")
            return self

        print("[sandbox] Starting infrastructure...")
        self._ensure_directories()
        self._start_server()
        self._wait_for_health()
        self._save_state()
        print(f"[sandbox] Started at {self.config.api_url}")
        return self

    def is_running(self) -> bool:
        """Check if the sandbox is currently running."""
        state = self._load_state()
        if not state.running or state.pid is None:
            return False

        # Check if process is still alive
        if not self._is_process_alive(state.pid):
            return False

        # Check if API is responding
        try:
            with urllib.request.urlopen(
                f"{self.config.api_url}/health", timeout=2
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    def check_upgrades_needed(self) -> dict:
        """Check if database or package upgrades are needed.

        Returns:
            dict with keys: db_upgrade_needed, package_upgrade_needed,
                           current_version, current_revision
        """
        result = {
            "db_upgrade_needed": False,
            "package_upgrade_needed": False,
            "current_version": None,
            "current_revision": None,
        }

        # Check database revision
        try:
            from optaic.runtime.upgrade_manager import read_alembic_revision

            result["current_revision"] = read_alembic_revision(self.config.database_url)
        except Exception:
            result["db_upgrade_needed"] = True

        # Check package version
        try:
            from optaic import __version__

            result["current_version"] = __version__
        except Exception:
            pass

        return result

    def apply_upgrades(self, dry_run: bool = False) -> dict:
        """Apply any pending database migrations.

        Args:
            dry_run: If True, only report what would be done

        Returns:
            dict with upgrade results
        """
        from optaic.runtime.upgrade_manager import migrate_db, read_alembic_revision

        result = {"applied": False, "before": None, "after": None}

        try:
            result["before"] = read_alembic_revision(self.config.database_url)
        except Exception:
            result["before"] = None

        if not dry_run:
            migrate_db(self.config.database_url)
            result["after"] = read_alembic_revision(self.config.database_url)
            result["applied"] = result["before"] != result["after"]

        return result

    def stop(self) -> None:
        """Stop the sandbox server."""
        state = self._load_state()
        if state.pid:
            try:
                import signal

                os.kill(state.pid, signal.SIGTERM)
                time.sleep(2)
            except Exception:
                pass

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        self._state = SandboxState(running=False)
        self._save_state()
        print("[sandbox] Stopped")

    def reset(self, keep_data: bool = False) -> None:
        """Reset the sandbox completely.

        Args:
            keep_data: If True, keep database and artifacts, just restart
        """
        self.stop()

        if not keep_data:
            # Remove entire data directory
            if self.config.data_dir.exists():
                shutil.rmtree(self.config.data_dir, ignore_errors=True)
            print("[sandbox] Data directory cleared")

    def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        (self.config.data_dir / "state").mkdir(exist_ok=True)
        (self.config.data_dir / "logs").mkdir(exist_ok=True)

    def _start_server(self) -> None:
        """Start the optaic server process."""
        env = os.environ.copy()
        env["DATABASE_URL"] = self.config.database_url
        env["OPTAIC_DATA_DIR"] = str(self.config.data_dir)
        env["CENTRIFUGO_API_KEY"] = "test-sandbox-api-key"
        env["CENTRIFUGO_TOKEN_SECRET"] = "test-sandbox-token-secret-32chars"
        env["PYTHONUNBUFFERED"] = "1"

        cmd = [
            sys.executable,
            "-m",
            "optaic",
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.config.api_port),
        ]

        if self.config.with_prefect:
            cmd.extend(
                ["--with-prefect", "--prefect-port", str(self.config.prefect_port)]
            )
        if self.config.with_mlflow:
            cmd.extend(["--with-mlflow", "--mlflow-port", str(self.config.mlflow_port)])
        if not self.config.with_worker:
            cmd.append("--no-worker")
        if not self.config.with_agent:
            cmd.append("--no-agent")

        log_file = self.config.data_dir / "logs" / "server.log"
        with open(log_file, "w") as f:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=f,
                stderr=subprocess.STDOUT,
            )

        self._state = SandboxState(
            running=True,
            pid=self._process.pid,
            api_url=self.config.api_url,
            prefect_api_url=self.config.prefect_api_url
            if self.config.with_prefect
            else None,
            mlflow_tracking_uri=self.config.mlflow_tracking_uri
            if self.config.with_mlflow
            else None,
            centrifugo_url=self.config.centrifugo_url,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def _wait_for_health(self, timeout: float = 120) -> None:
        """Wait for the server to become healthy."""
        health_url = f"{self.config.api_url}/health"
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=2) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                pass
            time.sleep(1)

        raise RuntimeError(f"Sandbox did not become healthy within {timeout}s")

    def _load_state(self) -> SandboxState:
        """Load state from disk."""
        if not self.config.state_file.exists():
            return SandboxState()

        try:
            data = json.loads(self.config.state_file.read_text())
            return SandboxState.from_dict(data)
        except Exception:
            return SandboxState()

    def _save_state(self) -> None:
        """Save state to disk."""
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_file.write_text(json.dumps(self.state.to_dict(), indent=2))

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still running."""
        if sys.platform == "win32":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False


# Global sandbox instance
_sandbox: Optional[SandboxManager] = None


def get_sandbox(config: Optional[SandboxConfig] = None) -> SandboxManager:
    """Get or create the global test sandbox.

    Args:
        config: Optional configuration. Only used if creating new sandbox.

    Returns:
        The test sandbox instance, started if not already running.
    """
    global _sandbox

    if _sandbox is None:
        _sandbox = SandboxManager(config)

    _sandbox.ensure_running()
    return _sandbox


def stop_sandbox() -> None:
    """Stop the global sandbox."""
    global _sandbox
    if _sandbox:
        _sandbox.stop()
        _sandbox = None


def reset_sandbox(keep_data: bool = False) -> None:
    """Reset the global sandbox."""
    global _sandbox
    if _sandbox:
        _sandbox.reset(keep_data=keep_data)
        _sandbox = None


# CLI for sandbox management
def main():
    """CLI for managing the test sandbox."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage OptAIC test sandbox")
    parser.add_argument("action", choices=["start", "stop", "status", "reset", "logs"])
    parser.add_argument("--keep-data", action="store_true", help="Keep data on reset")
    parser.add_argument("--api-port", type=int, default=19080, help="API port")
    args = parser.parse_args()

    config = SandboxConfig(api_port=args.api_port)
    sandbox = SandboxManager(config)

    if args.action == "start":
        sandbox.ensure_running()
        print(f"API: {sandbox.api_url}")
        print(f"Prefect: {sandbox.prefect_api_url}")
        print(f"MLflow: {sandbox.mlflow_tracking_uri}")

    elif args.action == "stop":
        sandbox.stop()

    elif args.action == "status":
        if sandbox.is_running():
            print("Status: RUNNING")
            state = sandbox.state
            print(f"PID: {state.pid}")
            print(f"API: {state.api_url}")
            print(f"Started: {state.started_at}")

            # Check upgrades
            upgrades = sandbox.check_upgrades_needed()
            print(f"Version: {upgrades['current_version']}")
            print(f"DB Revision: {upgrades['current_revision']}")
            if upgrades["db_upgrade_needed"]:
                print("WARNING: Database upgrade needed!")
        else:
            print("Status: STOPPED")

    elif args.action == "reset":
        sandbox.reset(keep_data=args.keep_data)
        print("Sandbox reset complete")

    elif args.action == "logs":
        log_file = config.data_dir / "logs" / "server.log"
        if log_file.exists():
            # Tail last 50 lines
            lines = log_file.read_text().splitlines()[-50:]
            for line in lines:
                print(line)
        else:
            print("No logs available")


if __name__ == "__main__":
    main()
