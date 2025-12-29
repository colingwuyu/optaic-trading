from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "apps" / "web"
DEFAULT_API_PORT = "8081"


def _with_pythonpath(env: dict[str, str]) -> dict[str, str]:
    updated = env.copy()
    root_str = str(ROOT)
    existing = updated.get("PYTHONPATH")
    updated["PYTHONPATH"] = (
        root_str if not existing else root_str + os.pathsep + existing
    )
    return updated


def _python_cmd(args: list[str]) -> list[str]:
    return [sys.executable, *args]


def _npm_cmd(args: list[str]) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", "npm", *args]
    return ["npm", *args]


def _ensure_tool(tool: str) -> None:
    if shutil.which(tool) is None:
        raise FileNotFoundError(f"{tool} not found on PATH.")


def _start(
    name: str,
    cmd: list[str],
    cwd: Path | None,
    env: dict[str, str],
) -> subprocess.Popen:
    print(f"[dev] starting {name}")
    return subprocess.Popen(cmd, cwd=cwd, env=env)


def _run_migrations(env: dict[str, str]) -> None:
    print("[dev] running migrations")
    cmd = _python_cmd(["-m", "alembic", "-c", "libs/db/alembic.ini", "upgrade", "head"])
    for attempt in range(1, 11):
        try:
            subprocess.run(cmd, cwd=ROOT, env=env, check=True)
            return
        except subprocess.CalledProcessError as exc:
            if attempt == 10:
                raise exc
            time.sleep(2)


def _terminate(processes: list[subprocess.Popen]) -> None:
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()

    deadline = time.time() + 5
    for proc in processes:
        if proc.poll() is not None:
            continue
        remaining = deadline - time.time()
        if remaining <= 0:
            proc.kill()
            continue
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    _ensure_tool("npm")
    if not WEB_DIR.is_dir():
        raise FileNotFoundError(f"Web app directory not found: {WEB_DIR}")

    api_port = os.environ.get("DEV_API_PORT", DEFAULT_API_PORT)
    web_port = os.environ.get("DEV_WEB_PORT", "5173")

    env = _with_pythonpath(os.environ)
    env.update(
        {
            "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
            "REDIS_URL": "redis://localhost:6379/0",
            "APP_ENV": "local",
            "LOG_LEVEL": "INFO",
            "CENTRIFUGO_URL": "http://localhost:8001",
            "CENTRIFUGO_API_KEY": "dev-api-key",
            "CENTRIFUGO_HMAC_SECRET": "dev-secret-change-me",
            "S3_ENDPOINT": "http://localhost:9000",
            "S3_ACCESS_KEY": "minioadmin",
            "S3_SECRET_KEY": "minioadmin",
            "S3_BUCKET": "attachments",
            "S3_REGION": "us-east-1",
            "AGENT_API_BASE_URL": f"http://localhost:{api_port}",
            "AGENT_POLL_INTERVAL": "2",
        }
    )

    web_env = env.copy()
    web_env.update(
        {
            "VITE_API_BASE_URL": f"http://localhost:{api_port}",
            "VITE_CENTRIFUGO_URL": "ws://localhost:8001/connection/websocket",
        }
    )

    processes: list[subprocess.Popen] = []

    def _handle_signal(_signum, _frame) -> None:
        _terminate(processes)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        _run_migrations(env)
        processes.append(
            _start(
                "api",
                _python_cmd(
                    [
                        "-m",
                        "uvicorn",
                        "apps.api.main:app",
                        "--reload",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        api_port,
                        "--reload-dir",
                        "apps/api",
                        "--reload-dir",
                        "libs",
                    ]
                ),
                ROOT,
                env,
            )
        )
        processes.append(
            _start("worker", _python_cmd(["-m", "apps.worker.main"]), ROOT, env)
        )
        processes.append(
            _start("agent", _python_cmd(["-m", "apps.agent.main"]), ROOT, env)
        )
        processes.append(
                _start(
                    "web",
                    _npm_cmd(
                        ["run", "dev", "--", "--host", "127.0.0.1", "--port", web_port]
                    ),
                    WEB_DIR,
                    web_env,
                )
            )

        while True:
            for proc in processes:
                code = proc.poll()
                if code is not None:
                    _terminate(processes)
                    return code
            time.sleep(0.5)
    finally:
        _terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
