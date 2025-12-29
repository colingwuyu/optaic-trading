"""
Consolidated runtime state management.

Two state files:
- installed.json: What is installed/configured (persisted across restarts)
- services_state.json: What is currently running (runtime-only)
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from optaic.runtime.runtime_config import RuntimeConfig
from optaic.version import get_version


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_optaic_version() -> str:
    """Get current OptAIC version."""
    try:
        return get_version()
    except Exception:
        return "unknown"



# ─────────────────────────────────────────────────────────────
# Installed state (what is configured)
# ─────────────────────────────────────────────────────────────


@dataclass
class ComponentInfo:
    """Information about an installed component."""

    name: str
    version: str | None
    mode: Literal["local", "remote", "disabled"]
    port: int | None = None
    data_path: str | None = None
    last_upgraded_at: str | None = None


@dataclass
class InstalledState:
    """State of what is installed/configured."""

    optaic_version: str
    python_version: str
    platform: str
    data_dir: str
    updated_at: str
    components: dict[str, ComponentInfo]
    ports: dict[str, int]


def get_installed_state(config: RuntimeConfig) -> InstalledState:
    """
    Build installed state from current configuration.

    Args:
        config: RuntimeConfig

    Returns:
        InstalledState with all component info
    """
    data_dir = config.data_dir
    components: dict[str, ComponentInfo] = {}
    ports: dict[str, int] = {}

    # Prefect
    prefect_version = _get_prefect_version()
    prefect_mode = config.prefect.mode
    components["prefect"] = ComponentInfo(
        name="prefect",
        version=prefect_version,
        mode=prefect_mode,
        port=config.prefect.port if prefect_mode == "local" else None,
        data_path=str(data_dir / "engines" / "prefect") if prefect_mode == "local" else None,
    )
    if prefect_mode == "local":
        ports["prefect"] = config.prefect.port

    # MLflow
    mlflow_version = _get_mlflow_version()
    mlflow_mode = config.mlflow.mode
    components["mlflow"] = ComponentInfo(
        name="mlflow",
        version=mlflow_version,
        mode=mlflow_mode,
        port=config.mlflow.port if mlflow_mode == "local" else None,
        data_path=str(data_dir / "engines" / "mlflow") if mlflow_mode == "local" else None,
    )
    if mlflow_mode == "local":
        ports["mlflow"] = config.mlflow.port

    # Centrifugo (check if binary exists)
    centrifugo_version = _get_centrifugo_version(data_dir)
    components["centrifugo"] = ComponentInfo(
        name="centrifugo",
        version=centrifugo_version,
        mode="local" if centrifugo_version else "disabled",
        data_path=str(data_dir / "centrifugo") if centrifugo_version else None,
    )

    # Redis (check if configured)
    redis_version = _get_redis_version()
    components["redis"] = ComponentInfo(
        name="redis",
        version=redis_version,
        mode="local" if redis_version else "disabled",
    )

    return InstalledState(
        optaic_version=_get_optaic_version(),
        python_version=platform.python_version(),
        platform=platform.system(),
        data_dir=str(data_dir),
        updated_at=_utc_now(),
        components=components,
        ports=ports,
    )


def write_installed_state(config: RuntimeConfig) -> Path:
    """
    Write installed state to DATA_DIR/state/installed.json.

    Returns:
        Path to the written file
    """
    state = get_installed_state(config)
    state_path = config.data_dir / "state" / "installed.json"
    _atomic_write_json(state_path, _installed_state_to_dict(state))
    return state_path


def load_installed_state(data_dir: Path) -> InstalledState | None:
    """Load installed state from disk."""
    state_path = data_dir / "state" / "installed.json"
    if not state_path.exists():
        return None

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return _dict_to_installed_state(data)
    except Exception:
        return None


def _installed_state_to_dict(state: InstalledState) -> dict:
    """Convert InstalledState to JSON-serializable dict."""
    return {
        "optaic_version": state.optaic_version,
        "python_version": state.python_version,
        "platform": state.platform,
        "data_dir": state.data_dir,
        "updated_at": state.updated_at,
        "components": {
            name: {
                "name": comp.name,
                "version": comp.version,
                "mode": comp.mode,
                "port": comp.port,
                "data_path": comp.data_path,
                "last_upgraded_at": comp.last_upgraded_at,
            }
            for name, comp in state.components.items()
        },
        "ports": state.ports,
    }


def _dict_to_installed_state(data: dict) -> InstalledState:
    """Convert dict to InstalledState."""
    components = {}
    for name, comp_data in data.get("components", {}).items():
        components[name] = ComponentInfo(
            name=comp_data.get("name", name),
            version=comp_data.get("version"),
            mode=comp_data.get("mode", "disabled"),
            port=comp_data.get("port"),
            data_path=comp_data.get("data_path"),
            last_upgraded_at=comp_data.get("last_upgraded_at"),
        )

    return InstalledState(
        optaic_version=data.get("optaic_version", "unknown"),
        python_version=data.get("python_version", "unknown"),
        platform=data.get("platform", "unknown"),
        data_dir=data.get("data_dir", ""),
        updated_at=data.get("updated_at", ""),
        components=components,
        ports=data.get("ports", {}),
    )


# ─────────────────────────────────────────────────────────────
# Services state (what is running)
# ─────────────────────────────────────────────────────────────


@dataclass
class ServiceRunState:
    """Runtime state of a single service."""

    name: str
    status: Literal["running", "stopped", "starting", "error", "disabled"]
    pid: int | None = None
    port: int | None = None
    url: str | None = None
    started_at: str | None = None
    last_health_check: str | None = None
    healthy: bool | None = None


@dataclass
class ServicesState:
    """State of all running services."""

    updated_at: str
    services: dict[str, ServiceRunState]


def write_services_state(
    data_dir: Path,
    services: dict[str, ServiceRunState],
) -> Path:
    """
    Write services state to DATA_DIR/state/services_state.json.

    This is runtime-only and overwritten on each startup.

    Returns:
        Path to the written file
    """
    state = ServicesState(
        updated_at=_utc_now(),
        services=services,
    )
    state_path = data_dir / "state" / "services_state.json"
    _atomic_write_json(state_path, _services_state_to_dict(state))
    return state_path


def load_services_state(data_dir: Path) -> ServicesState | None:
    """Load services state from disk."""
    state_path = data_dir / "state" / "services_state.json"
    if not state_path.exists():
        return None

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return _dict_to_services_state(data)
    except Exception:
        return None


def update_service_health(
    data_dir: Path,
    name: str,
    healthy: bool,
) -> None:
    """Update health check timestamp for a service."""
    state = load_services_state(data_dir)
    if state is None:
        return

    if name in state.services:
        state.services[name].last_health_check = _utc_now()
        state.services[name].healthy = healthy
        write_services_state(data_dir, state.services)


def _services_state_to_dict(state: ServicesState) -> dict:
    """Convert ServicesState to JSON-serializable dict."""
    return {
        "updated_at": state.updated_at,
        "services": {
            name: {
                "name": svc.name,
                "status": svc.status,
                "pid": svc.pid,
                "port": svc.port,
                "url": svc.url,
                "started_at": svc.started_at,
                "last_health_check": svc.last_health_check,
                "healthy": svc.healthy,
            }
            for name, svc in state.services.items()
        },
    }


def _dict_to_services_state(data: dict) -> ServicesState:
    """Convert dict to ServicesState."""
    services = {}
    for name, svc_data in data.get("services", {}).items():
        services[name] = ServiceRunState(
            name=svc_data.get("name", name),
            status=svc_data.get("status", "stopped"),
            pid=svc_data.get("pid"),
            port=svc_data.get("port"),
            url=svc_data.get("url"),
            started_at=svc_data.get("started_at"),
            last_health_check=svc_data.get("last_health_check"),
            healthy=svc_data.get("healthy"),
        )

    return ServicesState(
        updated_at=data.get("updated_at", ""),
        services=services,
    )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomically write JSON to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _get_prefect_version() -> str | None:
    """Get installed Prefect version."""
    try:
        import prefect
        return getattr(prefect, "__version__", None)
    except ImportError:
        return None


def _get_mlflow_version() -> str | None:
    """Get installed MLflow version."""
    try:
        import mlflow
        return getattr(mlflow, "__version__", None)
    except ImportError:
        return None


def _get_centrifugo_version(data_dir: Path) -> str | None:
    """Get Centrifugo version from manifest."""
    manifest_path = data_dir / "centrifugo" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest.get("version")
    except Exception:
        return None


def _get_redis_version() -> str | None:
    """Get Redis version if available."""
    try:
        import subprocess
        result = subprocess.run(
            ["redis-server", "--version"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if result.returncode == 0:
            # Parse "Redis server v=7.0.0 ..."
            for part in result.stdout.split():
                if part.startswith("v="):
                    return part[2:]
        return None
    except Exception:
        return None
