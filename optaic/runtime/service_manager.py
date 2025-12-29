from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from optaic.runtime.runtime_config import MlflowConfig, PrefectConfig
from optaic.runtime.upgrade_manager import (
    acquire_lock,
    load_installed_state,
    LockHandle,
    write_installed_state,
)


@dataclass
class ServiceProcess:
    """Internal tracking of a running subprocess."""
    name: str
    process: subprocess.Popen
    pid_path: Path
    log_path: Path | None = None


@dataclass
class ServiceState:
    """Runtime state of a managed service for health reporting."""
    name: str
    pid: int | None
    status: Literal["running", "stopped", "starting", "failed", "unknown"]
    started_at: str | None = None
    port: int | None = None
    url: str | None = None
    healthcheck_ok: bool | None = None
    last_healthcheck_at: str | None = None
    error: str | None = None


class ServiceManager:
    """
    Manages lifecycle of OptAIC sidecar services.

    Features:
    - PID files under DATA_DIR/state/pids/
    - Log files under DATA_DIR/logs/
    - Global lock for exclusive operations
    - Health reporting and state persistence
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.processes: list[ServiceProcess] = []
        self.log_threads: list[threading.Thread] = []
        self.prefect_api_url: str | None = None
        self.mlflow_tracking_uri: str | None = None
        self._lock: LockHandle | None = None
        self._started_at: dict[str, str] = {}
        self._ports: dict[str, int] = {}

    # ─────────────────────────────────────────────────────────────
    # Directory and layout management
    # ─────────────────────────────────────────────────────────────

    def ensure_directories(self) -> None:
        """Create required directories under DATA_DIR."""
        (self.data_dir / "state" / "pids").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)

    def _pids_dir(self) -> Path:
        return self.data_dir / "state" / "pids"

    def _logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def _services_state_path(self) -> Path:
        return self.data_dir / "state" / "services_state.json"

    def _ports_path(self) -> Path:
        return self.data_dir / "state" / "ports.json"

    # ─────────────────────────────────────────────────────────────
    # Lock management
    # ─────────────────────────────────────────────────────────────

    def acquire_global_lock(self) -> LockHandle:
        """Acquire exclusive lock for service operations."""
        self._lock = acquire_lock(self.data_dir)
        return self._lock

    def release_lock(self) -> None:
        """Release the global lock if held."""
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    # ─────────────────────────────────────────────────────────────
    # Port reservation
    # ─────────────────────────────────────────────────────────────

    def reserve_ports(self, ports: dict[str, int]) -> None:
        """Reserve ports for services."""
        self._ports.update(ports)
        self._ports_path().parent.mkdir(parents=True, exist_ok=True)
        payload = {"reserved_at": _utc_now(), "ports": self._ports}
        tmp_path = self._ports_path().with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self._ports_path())

    def load_reserved_ports(self) -> dict[str, int]:
        """Load previously reserved ports."""
        if not self._ports_path().exists():
            return {}
        try:
            payload = json.loads(self._ports_path().read_text(encoding="utf-8"))
            return payload.get("ports", {})
        except Exception:
            return {}

    # ─────────────────────────────────────────────────────────────
    # Health and state reporting
    # ─────────────────────────────────────────────────────────────

    def health_report(self) -> dict[str, ServiceState]:
        """Generate health report for all tracked services."""
        report: dict[str, ServiceState] = {}
        for proc in self.processes:
            is_alive = proc.process.poll() is None
            healthcheck_ok = None
            url = None

            # Determine health URL based on service name
            if "prefect" in proc.name:
                url = self.prefect_api_url
                if url and is_alive:
                    healthcheck_ok = _http_ok(url.replace("/api", "/api/health"))
            elif "mlflow" in proc.name:
                url = self.mlflow_tracking_uri
                if url and is_alive:
                    healthcheck_ok = _http_ok(url + "/health")

            report[proc.name] = ServiceState(
                name=proc.name,
                pid=proc.process.pid,
                status="running" if is_alive else "stopped",
                started_at=self._started_at.get(proc.name),
                port=self._ports.get(proc.name),
                url=url,
                healthcheck_ok=healthcheck_ok,
                last_healthcheck_at=_utc_now() if healthcheck_ok is not None else None,
            )
        return report

    def write_services_state_json(self) -> None:
        """Write current services state to services_state.json."""
        report = self.health_report()
        payload = {
            "updated_at": _utc_now(),
            "services": {
                name: {
                    "name": state.name,
                    "pid": state.pid,
                    "status": state.status,
                    "started_at": state.started_at,
                    "port": state.port,
                    "url": state.url,
                    "healthcheck_ok": state.healthcheck_ok,
                    "last_healthcheck_at": state.last_healthcheck_at,
                    "error": state.error,
                }
                for name, state in report.items()
            },
        }
        state_path = self._services_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(state_path)

    def load_services_state(self) -> dict[str, ServiceState]:
        """Load services state from file."""
        state_path = self._services_state_path()
        if not state_path.exists():
            return {}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            services = payload.get("services", {})
            return {
                name: ServiceState(
                    name=data.get("name", name),
                    pid=data.get("pid"),
                    status=data.get("status", "unknown"),
                    started_at=data.get("started_at"),
                    port=data.get("port"),
                    url=data.get("url"),
                    healthcheck_ok=data.get("healthcheck_ok"),
                    last_healthcheck_at=data.get("last_healthcheck_at"),
                    error=data.get("error"),
                )
                for name, data in services.items()
            }
        except Exception:
            return {}


    def start_prefect(self, config: PrefectConfig) -> str | None:
        if not config.enabled:
            return None

        if config.api_url:
            self.prefect_api_url = config.api_url
            self._record_service(
                name="prefect",
                version=_prefect_version(),
                bind_host=_host_from_url(config.api_url),
                port=_port_from_url(config.api_url),
                home_paths={"home_dir": str(config.home_dir or "")},
                url=config.api_url,
                mode="remote",
            )
            return self.prefect_api_url

        home_dir = config.home_dir or (self.data_dir / "prefect")
        home_dir.mkdir(parents=True, exist_ok=True)

        desired_port = config.port
        client_host = _client_host(config.bind_host)
        probe_urls = _prefect_health_urls(client_host, desired_port)
        port, existing = _resolve_port(config.bind_host, desired_port, probe_urls)
        api_url = _prefect_api_url(client_host, port)
        health_urls = _prefect_health_urls(client_host, port)
        self.prefect_api_url = api_url

        if existing:
            self._record_service(
                name="prefect",
                version=_prefect_version(),
                bind_host=config.bind_host,
                port=port,
                home_paths={"home_dir": str(home_dir)},
                url=api_url,
                mode="existing",
            )
            return api_url

        env = os.environ.copy()
        env["PREFECT_HOME"] = str(home_dir)
        env["PREFECT_API_URL"] = api_url
        env.setdefault("PREFECT_MEMO_STORE_PATH", str(home_dir / "memo_store.toml"))
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        server_cmd = [
            sys.executable,
            "-m",
            "prefect",
            "server",
            "start",
            "--host",
            config.bind_host,
            "--port",
            str(port),
        ]
        server_proc = subprocess.Popen(
            server_cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._track_process("prefect-server", server_proc)
        _wait_for_http(health_urls, timeout_seconds=30)

        self._ensure_prefect_work_pool(config, env)

        if config.worker_limit > 0:
            worker_cmd = [
                sys.executable,
                "-m",
                "prefect",
                "worker",
                "start",
                "--pool",
                config.work_pool,
                "--type",
                "process",
                "--limit",
                str(config.worker_limit),
            ]
            worker_proc = subprocess.Popen(
                worker_cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._track_process("prefect-worker", worker_proc)

        self._record_service(
            name="prefect",
            version=_prefect_version(),
            bind_host=config.bind_host,
            port=port,
            home_paths={"home_dir": str(home_dir)},
            url=api_url,
            mode="local",
        )
        return api_url

    def start_mlflow(self, config: MlflowConfig) -> str | None:
        if not config.enabled:
            return None

        if config.tracking_uri:
            self.mlflow_tracking_uri = config.tracking_uri
            self._record_service(
                name="mlflow",
                version=_mlflow_version(),
                bind_host=_host_from_url(config.tracking_uri),
                port=_port_from_url(config.tracking_uri),
                home_paths={
                    "backend_store_uri": config.backend_store_uri,
                    "artifact_root": str(config.default_artifact_root or ""),
                },
                url=config.tracking_uri,
                mode="remote",
            )
            return self.mlflow_tracking_uri

        desired_port = config.port
        client_host = _client_host(config.bind_host)
        probe_urls = [f"http://{client_host}:{desired_port}/"]
        port, existing = _resolve_port(config.bind_host, desired_port, probe_urls)
        tracking_uri = f"http://{client_host}:{port}"
        health_urls = [f"http://{client_host}:{port}/"]
        self.mlflow_tracking_uri = tracking_uri

        if existing:
            self._record_service(
                name="mlflow",
                version=_mlflow_version(),
                bind_host=config.bind_host,
                port=port,
                home_paths={
                    "backend_store_uri": config.backend_store_uri,
                    "artifact_root": str(config.default_artifact_root or ""),
                },
                url=tracking_uri,
                mode="existing",
            )
            return tracking_uri

        backend_uri = config.backend_store_uri
        artifact_root = config.default_artifact_root or (
            self.data_dir / "mlflow" / "artifacts"
        )
        _ensure_backend_directory(backend_uri)
        _ensure_artifact_path(artifact_root)

        cmd = [
            sys.executable,
            "-m",
            "mlflow",
            "server",
            "--host",
            config.bind_host,
            "--port",
            str(port),
            "--backend-store-uri",
            backend_uri,
        ]
        if config.artifacts_mode == "direct":
            cmd.extend(
                [
                    "--default-artifact-root",
                    str(artifact_root),
                    "--no-serve-artifacts",
                ]
            )
        else:
            cmd.extend(["--artifacts-destination", str(artifact_root)])

        proc = subprocess.Popen(
            cmd,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._track_process("mlflow", proc)
        _wait_for_http(health_urls, timeout_seconds=30)

        self._record_service(
            name="mlflow",
            version=_mlflow_version(),
            bind_host=config.bind_host,
            port=port,
            home_paths={
                "backend_store_uri": backend_uri,
                "artifact_root": str(artifact_root),
            },
            url=tracking_uri,
            mode="local",
        )
        return tracking_uri

    def stop_all(self, timeout_seconds: float = 5.0, *, reverse_order: bool = True) -> list[ServiceState]:
        """Stop all managed services.

        Args:
            timeout_seconds: Time to wait for graceful shutdown per service.
            reverse_order: If True, stop in reverse order of startup.

        Returns:
            List of ServiceState for each stopped service.
        """
        results: list[ServiceState] = []
        procs = list(reversed(self.processes)) if reverse_order else list(self.processes)

        for proc in procs:
            if proc.process.poll() is None:
                proc.process.terminate()

        deadline = time.monotonic() + timeout_seconds
        for proc in procs:
            if proc.process.poll() is not None:
                self._remove_pidfile(proc.pid_path)
                results.append(ServiceState(name=proc.name, pid=proc.process.pid, status="stopped"))
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.process.kill()
            else:
                try:
                    proc.process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    proc.process.kill()
            self._remove_pidfile(proc.pid_path)
            results.append(ServiceState(name=proc.name, pid=proc.process.pid, status="stopped"))

        self.processes.clear()
        self.write_services_state_json()
        return results


    def _track_process(self, name: str, process: subprocess.Popen, port: int | None = None) -> None:
        """Track a started subprocess with pidfile and optional log streaming."""
        pid_path = self._pids_dir() / f"{name}.pid"
        log_path = self._logs_dir() / f"{name}.log"
        self._write_pidfile(pid_path, process.pid)
        self._started_at[name] = _utc_now()
        if port:
            self._ports[name] = port
        self.processes.append(ServiceProcess(name=name, process=process, pid_path=pid_path, log_path=log_path))
        self.log_threads.append(_stream_logs(process, f"[{name}]"))


    def _write_pidfile(self, path: Path, pid: int | None) -> None:
        if pid is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n", encoding="utf-8")

    def _remove_pidfile(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def _ensure_prefect_work_pool(self, config: PrefectConfig, env: dict[str, str]) -> None:
        cmd = [
            sys.executable,
            "-m",
            "prefect",
            "work-pool",
            "create",
            config.work_pool,
            "--type",
            "process",
            "--overwrite",
        ]
        subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _record_service(
        self,
        *,
        name: str,
        version: str,
        bind_host: str | None,
        port: int | None,
        home_paths: dict[str, str],
        url: str | None,
        mode: str,
    ) -> None:
        payload = load_installed_state(self.data_dir)
        services = dict(payload.get("services", {}))
        services[name] = {
            "name": name,
            "version": version,
            "bind_host": bind_host,
            "port": port,
            "ports": {"http": port} if port else {},
            "home_paths": {k: v for k, v in home_paths.items() if v},
            "last_start_time": _utc_now(),
            "mode": mode,
            "url": url,
        }
        payload["services"] = services
        write_installed_state(self.data_dir, payload)


class PrefectService:
    def __init__(self, manager: ServiceManager) -> None:
        self.manager = manager

    def start(self, config: PrefectConfig) -> str | None:
        return self.manager.start_prefect(config)


class MLflowService:
    def __init__(self, manager: ServiceManager) -> None:
        self.manager = manager

    def start(self, config: MlflowConfig) -> str | None:
        return self.manager.start_mlflow(config)


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


def _prefect_api_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/api"


def _prefect_health_urls(host: str, port: int) -> list[str]:
    return [
        f"http://{host}:{port}/api/health",
        f"http://{host}:{port}/api",
    ]


def _resolve_port(host: str, port: int, health_urls: list[str]) -> tuple[int, bool]:
    if _can_bind(host, port):
        return port, False
    if _http_ok_any(health_urls):
        return port, True
    return _find_free_port(host), False


def _can_bind(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def _find_free_port(host: str) -> int:
    try_host = host
    for candidate in (try_host, "127.0.0.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((candidate, 0))
                return sock.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("Failed to reserve a free port.")


def _wait_for_http(urls: list[str], timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _http_ok_any(urls):
            return
        time.sleep(0.5)
    raise RuntimeError("Service did not become healthy in time.")


def _http_ok_any(urls: list[str], timeout_seconds: float = 2.0) -> bool:
    for url in urls:
        if _http_ok(url, timeout_seconds=timeout_seconds):
            return True
    return False


def _http_ok(url: str, timeout_seconds: float = 2.0) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "optaic"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status < 400
    except Exception:
        return False


def _ensure_backend_directory(backend_uri: str) -> None:
    if backend_uri.startswith("sqlite:///"):
        path = Path(backend_uri.replace("sqlite:///", "", 1))
        path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_artifact_path(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return


def _prefect_version() -> str:
    try:
        import prefect  # type: ignore
    except Exception:
        return "unknown"
    return getattr(prefect, "__version__", "unknown")


def _mlflow_version() -> str:
    try:
        import mlflow  # type: ignore
    except Exception:
        return "unknown"
    return getattr(mlflow, "__version__", "unknown")


def _host_from_url(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except Exception:
        return None


def _port_from_url(url: str) -> int | None:
    try:
        return urlsplit(url).port
    except Exception:
        return None


def _client_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────


def cleanup_stale_pids(data_dir: Path) -> list[str]:
    """Remove pidfiles for processes that are no longer running."""
    pids_dir = data_dir / "state" / "pids"
    if not pids_dir.exists():
        return []

    cleaned: list[str] = []
    for pidfile in pids_dir.glob("*.pid"):
        try:
            pid = int(pidfile.read_text(encoding="utf-8").strip())
        except (ValueError, FileNotFoundError):
            pidfile.unlink(missing_ok=True)
            cleaned.append(pidfile.stem)
            continue

        if not _is_process_alive(pid):
            pidfile.unlink(missing_ok=True)
            cleaned.append(pidfile.stem)

    return cleaned


def get_service_status(data_dir: Path, name: str) -> ServiceState:
    """Get status of a service by name."""
    pidfile = data_dir / "state" / "pids" / f"{name}.pid"

    if not pidfile.exists():
        return ServiceState(name=name, pid=None, status="stopped")

    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (ValueError, FileNotFoundError):
        return ServiceState(name=name, pid=None, status="stopped")

    if not _is_process_alive(pid):
        return ServiceState(name=name, pid=pid, status="stopped")

    return ServiceState(name=name, pid=pid, status="running")


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
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

