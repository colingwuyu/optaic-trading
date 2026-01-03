"""
Service health checks (HTTP + TCP + readiness).

Provides structured health checking for OptAIC sidecar services:
- API: HTTP GET /healthz
- Centrifugo: HTTP GET /health or TCP fallback
- Redis: TCP check + optional PING
- Prefect: HTTP GET /api/health or /api
- MLflow: HTTP GET /
"""

from __future__ import annotations

import socket
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# Basic checks
# ─────────────────────────────────────────────────────────────


def tcp_check(host: str, port: int, timeout: float = 1.0) -> bool:
    """
    Check if a TCP port is accepting connections.

    Args:
        host: Host to connect to
        port: Port number
        timeout: Connection timeout in seconds

    Returns:
        True if connection successful, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            return True
    except (socket.timeout, socket.error, OSError):
        return False


def http_check(
    url: str,
    expect_status: tuple[int, ...] = (200, 204, 301, 302),
    timeout: float = 2.0,
) -> bool:
    """
    Check if an HTTP endpoint returns an expected status.

    Args:
        url: URL to check
        expect_status: Tuple of acceptable HTTP status codes
        timeout: Request timeout in seconds

    Returns:
        True if status is in expect_status, False otherwise
    """
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "optaic-health"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status in expect_status
    except Exception:
        return False


def redis_ping(host: str = "127.0.0.1", port: int = 6379, timeout: float = 1.0) -> bool:
    """
    Check Redis with PING command via redis-cli.

    Falls back to TCP check if redis-cli is unavailable.

    Args:
        host: Redis host
        port: Redis port
        timeout: Timeout in seconds

    Returns:
        True if Redis responds to PING, False otherwise
    """
    try:
        result = subprocess.run(
            ["redis-cli", "-h", host, "-p", str(port), "PING"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0 and "PONG" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # redis-cli not available, fall back to TCP check
        return tcp_check(host, port, timeout)


# ─────────────────────────────────────────────────────────────
# Service-specific health checks
# ─────────────────────────────────────────────────────────────


def check_api_health(host: str, port: int) -> bool:
    """Check OptAIC API health via /healthz endpoint."""
    return http_check(f"http://{host}:{port}/healthz", expect_status=(200,))


def check_centrifugo_health(host: str, port: int) -> bool:
    """
    Check Centrifugo health.

    Tries /health endpoint first, falls back to TCP check.
    """
    if http_check(f"http://{host}:{port}/health", expect_status=(200,)):
        return True
    # Fallback to TCP check (Centrifugo may not have /health)
    return tcp_check(host, port)


def check_redis_health(host: str, port: int) -> bool:
    """Check Redis health via PING or TCP."""
    return redis_ping(host, port)


def check_prefect_server_health(host: str, port: int) -> bool:
    """
    Check Prefect server health.

    Tries /api/health first, then /api as fallback.
    """
    if http_check(f"http://{host}:{port}/api/health", expect_status=(200,)):
        return True
    # Fallback to /api endpoint
    return http_check(f"http://{host}:{port}/api", expect_status=(200, 301, 302))


def check_prefect_worker_health(pid: int | None) -> bool:
    """
    Check Prefect worker health.

    Worker is considered healthy if the process is alive.
    """
    if pid is None:
        return False
    return _is_process_alive(pid)


def check_mlflow_health(host: str, port: int) -> bool:
    """Check MLflow health via root endpoint."""
    return http_check(f"http://{host}:{port}/", expect_status=(200,))


def _is_process_alive(pid: int) -> bool:
    """Check if a process is running."""
    import sys
    import os

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


# ─────────────────────────────────────────────────────────────
# Unified health report
# ─────────────────────────────────────────────────────────────


@dataclass
class ServiceHealth:
    """Health status of a single service."""

    name: str
    status: Literal["up", "down", "starting", "error", "disabled"]
    pid: int | None = None
    port: int | None = None
    url: str | None = None
    last_checked_at: str | None = None
    error: str | None = None


def check_service_health(
    name: str,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    pid: int | None = None,
    enabled: bool = True,
) -> ServiceHealth:
    """
    Check health of a named service.

    Args:
        name: Service name (api, centrifugo, redis, prefect-server, prefect-worker, mlflow)
        host: Service host
        port: Service port
        pid: Process ID (for process-based checks)
        enabled: Whether the service is enabled

    Returns:
        ServiceHealth with current status
    """
    if not enabled:
        return ServiceHealth(name=name, status="disabled")

    if port is None and name not in ("prefect-worker",):
        return ServiceHealth(name=name, status="error", error="Port not configured")

    url = None
    is_healthy = False

    try:
        if name == "api":
            url = f"http://{host}:{port}/healthz"
            is_healthy = check_api_health(host, port)
        elif name == "centrifugo":
            url = f"http://{host}:{port}/health"
            is_healthy = check_centrifugo_health(host, port)
        elif name == "redis":
            is_healthy = check_redis_health(host, port)
        elif name == "prefect-server":
            url = f"http://{host}:{port}/api/health"
            is_healthy = check_prefect_server_health(host, port)
        elif name == "prefect-worker":
            is_healthy = check_prefect_worker_health(pid)
        elif name == "mlflow":
            url = f"http://{host}:{port}/"
            is_healthy = check_mlflow_health(host, port)
        else:
            # Generic TCP check for unknown services
            if port:
                is_healthy = tcp_check(host, port)

        return ServiceHealth(
            name=name,
            status="up" if is_healthy else "down",
            pid=pid,
            port=port,
            url=url,
            last_checked_at=_utc_now(),
        )
    except Exception as exc:
        return ServiceHealth(
            name=name,
            status="error",
            pid=pid,
            port=port,
            url=url,
            last_checked_at=_utc_now(),
            error=str(exc),
        )


def get_security_warnings(bind_hosts: dict[str, str]) -> list[str]:
    """
    Generate security warnings for non-localhost bindings.

    Args:
        bind_hosts: Dict mapping service name to bind host

    Returns:
        List of warning messages
    """
    warnings: list[str] = []
    for name, host in bind_hosts.items():
        if host in ("0.0.0.0", "::"):
            warnings.append(
                f"SECURITY WARNING: {name} is bound to all interfaces ({host}). "
                "This exposes the service to the network."
            )
    return warnings


@dataclass
class RuntimeStatus:
    """Full runtime status for /system/runtime endpoint."""

    services: dict[str, dict]
    warnings: list[str]
    checked_at: str


def get_runtime_status(
    *,
    service_configs: dict[str, dict],
) -> RuntimeStatus:
    """
    Get complete runtime status for /system/runtime endpoint.

    Args:
        service_configs: Dict mapping service name to config with keys:
            - enabled: bool
            - host: str (bind host)
            - port: int | None
            - pid: int | None (for process-based services)

    Returns:
        RuntimeStatus with services health and warnings

    Example:
        status = get_runtime_status(
            service_configs={
                "api": {"enabled": True, "host": "127.0.0.1", "port": 8080},
                "prefect-server": {"enabled": True, "host": "127.0.0.1", "port": 4200},
                "mlflow": {"enabled": False, "host": "127.0.0.1", "port": 5000},
            }
        )
    """
    services: dict[str, dict] = {}
    bind_hosts: dict[str, str] = {}

    for name, config in service_configs.items():
        enabled = config.get("enabled", False)
        host = config.get("host", "127.0.0.1")
        port = config.get("port")
        pid = config.get("pid")

        if enabled:
            bind_hosts[name] = host

        health = check_service_health(
            name,
            host=host,
            port=port,
            pid=pid,
            enabled=enabled,
        )

        services[name] = {
            "status": health.status,
            "pid": health.pid,
            "port": health.port,
            "url": health.url,
            "last_checked_at": health.last_checked_at,
        }
        if health.error:
            services[name]["error"] = health.error

    warnings = get_security_warnings(bind_hosts)

    return RuntimeStatus(
        services=services,
        warnings=warnings,
        checked_at=_utc_now(),
    )


def runtime_status_to_dict(status: RuntimeStatus) -> dict:
    """Convert RuntimeStatus to JSON-serializable dict for API response."""
    return {
        "services": status.services,
        "warnings": status.warnings,
        "checked_at": status.checked_at,
    }
