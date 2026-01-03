from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from optaic.config import Settings
from optaic.runtime.centrifugo_manager import (
    CentrifugoConfig,
    CentrifugoManager,
    DEFAULT_CENTRIFUGO_VERSION,
    wait_until_ready,
)
from optaic.runtime.redis_manager import redis_process, start_redis, stop_redis
from optaic.runtime.runtime_config import MlflowConfig, PrefectConfig
from optaic.runtime.service_manager import ServiceManager
from optaic.runtime.upgrade_manager import (
    acquire_lock,
    apply_upgrades,
    ensure_data_layout,
    load_desired_manifest,
    load_installed_state,
    log_upgrade,
    migrate_db,
    platform_key,
    plan_upgrades,
    read_alembic_revision,
    set_upgrade_status,
    update_db_state,
    write_installed_state,
)


@dataclass(frozen=True)
class SupervisorConfig:
    data_dir: Path
    settings: Settings
    host: str
    port: int
    database_url: str
    start_worker: bool
    start_agent: bool
    open_browser: bool
    with_redis: bool
    redis_url: str | None
    redis_port: int
    redis_bind: str
    redis_version: str
    redis_flavor: str
    prefect: PrefectConfig
    mlflow: MlflowConfig


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen


def start_centrifugo(
    config: CentrifugoConfig,
    version: str,
    log_prefix: str,
    *,
    binary_path: Path | None = None,
) -> tuple[CentrifugoManager, ManagedProcess, threading.Thread]:
    manager = CentrifugoManager(config, version, binary_path=binary_path)
    process = manager.start(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        wait=False,
    )
    log_thread = _stream_logs(process, log_prefix)
    wait_until_ready(config.http_url)
    return manager, ManagedProcess("centrifugo", process), log_thread


def start_api(host: str, port: int, env: dict[str, str]) -> ManagedProcess:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    return _start_process("api", cmd, env, "[api]")


def start_worker(env: dict[str, str]) -> ManagedProcess:
    cmd = [sys.executable, "-m", "apps.worker.main"]
    return _start_process("worker", cmd, env, "[worker]")


def start_agent(env: dict[str, str]) -> ManagedProcess:
    cmd = [sys.executable, "-m", "apps.agent.main"]
    return _start_process("agent", cmd, env, "[agent]")


def run_supervisor(config: SupervisorConfig) -> int:
    processes: list[ManagedProcess] = []
    log_threads: list[threading.Thread] = []
    centrifugo_manager: CentrifugoManager | None = None
    resolved_redis_url: str | None = None
    lock_handle = None
    centrifugo_binary: Path | None = None
    centrifugo_version = DEFAULT_CENTRIFUGO_VERSION
    service_manager = ServiceManager(config.data_dir)
    prefect_api_url: str | None = None
    mlflow_tracking_uri: str | None = None
    os.environ.setdefault("OPTAIC_DATA_DIR", str(config.data_dir))

    def _shutdown() -> None:
        service_manager.stop_all()
        if centrifugo_manager is not None:
            centrifugo_manager.stop()
        stop_redis()
        _terminate(processes)
        _remove_server_pid(config.data_dir)
        if lock_handle is not None:
            lock_handle.release()

    def _signal_handler(_signum, _frame) -> None:
        _shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)

    try:
        ensure_data_layout(config.data_dir)
        try:
            lock_handle = acquire_lock(config.data_dir)
        except Exception as exc:
            print(str(exc))
            raise
        _write_server_pid(config.data_dir)
        set_upgrade_status(config.data_dir, "running")
        try:
            before_rev = read_alembic_revision(config.database_url)
        except Exception:
            before_rev = None
        print("Running database migrations...")
        try:
            migrate_db(config.database_url)
            after_rev = read_alembic_revision(config.database_url)
            log_upgrade(
                config.data_dir,
                action="db.migrate",
                outcome="success",
                before_version=before_rev,
                after_version=after_rev,
            )
        except Exception as exc:
            log_upgrade(
                config.data_dir,
                action="db.migrate",
                outcome="failed",
                before_version=before_rev,
                after_version=None,
                detail=str(exc),
            )
            set_upgrade_status(config.data_dir, "failed", error=str(exc))
            print("Database migrations failed.")
            print(f"DATABASE_URL={config.database_url}")
            if config.settings.mode == "prod":
                print(
                    "MODE=prod requires a reachable Postgres database. Set DATABASE_URL "
                    "and ensure the server is running."
                )
            else:
                print(
                    "Ensure the data directory is writable or delete a corrupted "
                    "SQLite database before retrying."
                )
            raise
        print("Migrations complete.")

        if (
            not config.settings.centrifugo_api_key
            or not config.settings.centrifugo_token_secret
        ):
            raise RuntimeError(
                "CENTRIFUGO_API_KEY and CENTRIFUGO_TOKEN_SECRET are required."
            )
        centrifugo_override = os.environ.get("OPTAIC_CENTRIFUGO_PATH")
        desired_manifest = load_desired_manifest()
        installed_state = load_installed_state(config.data_dir)
        try:
            actions = plan_upgrades(
                desired_manifest,
                installed_state,
                platform_key(),
                with_redis=config.with_redis,
                redis_url=config.redis_url,
                redis_flavor=config.redis_flavor,
                centrifugo_override=centrifugo_override,
            )
        except Exception as exc:
            print("Failed to plan infrastructure upgrades.")
            if (
                config.with_redis
                and not sys.platform.startswith("win")
                and not config.redis_url
            ):
                print(
                    "Redis is enabled without --redis-url. Provide --redis-url or "
                    "disable --with-redis on non-Windows."
                )
            print(str(exc))
            raise
        if actions:
            print("Applying infrastructure upgrades...")
        try:
            installed_state = apply_upgrades(
                actions,
                config.data_dir,
                installed_state,
                desired_manifest,
                with_redis=config.with_redis,
                redis_url=config.redis_url,
                redis_flavor=config.redis_flavor,
                centrifugo_override=centrifugo_override,
            )
        except Exception as exc:
            log_upgrade(
                config.data_dir,
                action="infra.apply",
                outcome="failed",
                detail=str(exc),
            )
            set_upgrade_status(config.data_dir, "failed", error=str(exc))
            print("Failed to apply infrastructure upgrades.")
            print(str(exc))
            raise
        installed_state = update_db_state(installed_state, config.database_url)
        write_installed_state(config.data_dir, installed_state)
        set_upgrade_status(config.data_dir, "done")
        centrifugo_state = installed_state.get("tools", {}).get("centrifugo", {})
        centrifugo_path = centrifugo_state.get("path")
        centrifugo_version = (
            centrifugo_state.get("version") or DEFAULT_CENTRIFUGO_VERSION
        )
        if centrifugo_path:
            candidate = Path(centrifugo_path)
            if candidate.exists():
                centrifugo_binary = candidate
        if config.with_redis:
            try:
                resolved_redis_url = start_redis(
                    config.with_redis,
                    config.redis_url,
                    config.redis_bind,
                    config.redis_port,
                    config.redis_version,
                    config.redis_flavor,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            except Exception as exc:
                print("Failed to start or connect to Redis.")
                print(str(exc))
                raise
            redis_proc = redis_process()
            if redis_proc:
                print(
                    "Starting Redis (embedded) on "
                    f"{config.redis_bind}:{config.redis_port}..."
                )
                log_threads.append(_stream_logs(redis_proc, "[redis]"))
            else:
                print(f"Using Redis at {resolved_redis_url}")
        else:
            print("Redis disabled.")

        try:
            prefect_api_url = service_manager.start_prefect(config.prefect)
        except Exception as exc:
            print("Failed to start Prefect.")
            print(str(exc))
            raise
        try:
            mlflow_tracking_uri = service_manager.start_mlflow(config.mlflow)
        except Exception as exc:
            print("Failed to start MLflow.")
            print(str(exc))
            raise

        for proc in service_manager.processes:
            processes.append(ManagedProcess(proc.name, proc.process))
        log_threads.extend(service_manager.log_threads)

        env = _build_env(
            config,
            redis_url=resolved_redis_url,
            prefect_api_url=prefect_api_url,
            mlflow_tracking_uri=mlflow_tracking_uri,
        )
        centrifugo_config = CentrifugoConfig(
            data_dir=config.data_dir,
            port=config.settings.centrifugo_port,
            api_key=config.settings.centrifugo_api_key,
            token_secret=config.settings.centrifugo_token_secret,
            allowed_origins=_allowed_origins(config.host, config.port),
            redis_url=resolved_redis_url,
        )
        engine_label = "redis" if resolved_redis_url else "memory"
        print(f"Starting Centrifugo ({engine_label} engine)...")
        try:
            centrifugo_manager, rt_process, rt_thread = start_centrifugo(
                centrifugo_config,
                centrifugo_version,
                "[rt]",
                binary_path=centrifugo_binary,
            )
        except Exception:
            print("Failed to start Centrifugo.")
            print(
                "If this is a fresh install, ensure network access or set "
                "OPTAIC_CENTRIFUGO_PATH to a local binary."
            )
            if resolved_redis_url:
                print(
                    "REDIS_URL is set. Ensure Redis is reachable and credentials "
                    "are correct."
                )
            raise
        processes.append(rt_process)
        log_threads.append(rt_thread)

        api_process = start_api(config.host, config.port, env)
        processes.append(api_process)

        if config.start_worker:
            processes.append(start_worker(env))
        if config.start_agent:
            processes.append(start_agent(env))

        if config.open_browser:
            _open_browser(_browser_url(config.host, config.port))

        while True:
            for proc in processes:
                if proc.process.poll() is not None:
                    _shutdown()
                    return proc.process.returncode or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()
        return 0
    finally:
        _shutdown()
        for thread in log_threads:
            thread.join(timeout=1)


def _build_env(
    config: SupervisorConfig,
    redis_url: str | None,
    *,
    prefect_api_url: str | None,
    mlflow_tracking_uri: str | None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["DATABASE_URL"] = config.database_url
    if redis_url:
        env["REDIS_URL"] = redis_url
    else:
        env.pop("REDIS_URL", None)
    if prefect_api_url:
        env["PREFECT_API_URL"] = prefect_api_url
        if config.prefect.home_dir:
            env["PREFECT_HOME"] = str(config.prefect.home_dir)
    else:
        env.pop("PREFECT_API_URL", None)
    if mlflow_tracking_uri:
        env["MLFLOW_TRACKING_URI"] = mlflow_tracking_uri
    else:
        env.pop("MLFLOW_TRACKING_URI", None)
    api_host = _local_host(config.host)
    env.setdefault("AGENT_API_BASE_URL", f"http://{api_host}:{config.port}")
    centrifugo_url = f"http://127.0.0.1:{config.settings.centrifugo_port}"
    env["CENTRIFUGO_URL"] = centrifugo_url
    env["CENTRIFUGO_API_KEY"] = config.settings.centrifugo_api_key or ""
    env["CENTRIFUGO_HMAC_SECRET"] = config.settings.centrifugo_token_secret or ""
    return env


def _start_process(
    name: str,
    cmd: list[str],
    env: dict[str, str],
    prefix: str,
) -> ManagedProcess:
    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _stream_logs(process, prefix)
    return ManagedProcess(name, process)


def _stream_logs(process: subprocess.Popen, prefix: str) -> threading.Thread:
    def _reader() -> None:
        if process.stdout is None:
            return
        for line in iter(process.stdout.readline, ""):
            text = line.rstrip()
            if text:
                print(f"{prefix} {text}", flush=True)
        process.stdout.close()

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def _terminate(processes: list[ManagedProcess], timeout: float = 5) -> None:
    for proc in processes:
        if proc.process.poll() is None:
            proc.process.terminate()

    deadline = time.time() + timeout
    for proc in processes:
        if proc.process.poll() is not None:
            continue
        remaining = deadline - time.time()
        if remaining <= 0:
            proc.process.kill()
            continue
        try:
            proc.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.process.kill()


def _allowed_origins(host: str, port: int) -> list[str]:
    origins = {f"http://{host}:{port}"}
    if host in {"127.0.0.1", "0.0.0.0", "::"}:
        origins.add(f"http://localhost:{port}")
    if host in {"localhost", "0.0.0.0", "::"}:
        origins.add(f"http://127.0.0.1:{port}")
    return sorted(origins)


def _browser_url(host: str, port: int) -> str:
    return f"http://{_local_host(host)}:{port}/"


def _local_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _open_browser(url: str) -> None:
    if sys.platform.startswith("win"):
        subprocess.Popen(["cmd", "/c", "start", "", url])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url])
    else:
        subprocess.Popen(["xdg-open", url])


def _write_server_pid(data_dir: Path) -> None:
    pid_path = data_dir / "state" / "server.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _remove_server_pid(data_dir: Path) -> None:
    pid_path = data_dir / "state" / "server.pid"
    try:
        pid_path.unlink()
    except FileNotFoundError:
        return
