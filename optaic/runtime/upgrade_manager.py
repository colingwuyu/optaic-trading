from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import asyncio
import json
import os
import platform
import shutil
from typing import Any, Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from optaic.runtime.migrate import run_migrations
from optaic.runtime.centrifugo_manager import ensure_centrifugo_binary
from optaic.runtime.infra_manifest import (
    get_asset,
    get_default_version,
    load_manifest,
)
from optaic.runtime.redis_manager import ensure_redis_binary, resolve_redis_mode

STATE_SCHEMA_VERSION = 1
DEFAULT_KEEP_VERSIONS = 2
UPGRADE_STATUS_DEFAULT = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "last_error": None,
}


@dataclass(frozen=True)
class UpgradeAction:
    tool: str
    version: str
    asset_url: str
    asset_sha256: str


@dataclass
class LockHandle:
    path: Path
    handle: Any

    def release(self) -> None:
        if self.handle is None:
            return
        _release_lock(self.handle)
        self.handle.close()
        self.handle = None


def ensure_data_layout(data_dir: Path) -> None:
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    (data_dir / "bin").mkdir(parents=True, exist_ok=True)
    (data_dir / "downloads").mkdir(parents=True, exist_ok=True)
    (data_dir / "state").mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    # Engine-specific directories (Prefect, MLflow)
    from optaic.runtime.engines_state import ensure_engines_layout

    ensure_engines_layout(data_dir)


def migrate_db(database_url: str) -> None:
    run_migrations(database_url)


def load_desired_manifest() -> dict[str, Any]:
    return load_manifest()


def load_installed_state(data_dir: Path) -> dict[str, Any]:
    state_path = data_dir / "state" / "installed.json"
    if not state_path.exists():
        return {"schema": STATE_SCHEMA_VERSION, "tools": {}, "db": {}}
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_installed_state(data_dir: Path, state: dict[str, Any]) -> None:
    state_path = data_dir / "state" / "installed.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["schema"] = STATE_SCHEMA_VERSION
    payload["installed_at"] = _utc_now()
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(state_path)


def acquire_lock(data_dir: Path) -> LockHandle:
    lock_path = data_dir / "state" / "lockfile"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    _acquire_lock(handle)
    return LockHandle(path=lock_path, handle=handle)


def read_upgrade_status(data_dir: Path) -> dict[str, Any]:
    status_path = data_dir / "state" / "upgrade_status.json"
    if not status_path.exists():
        return dict(UPGRADE_STATUS_DEFAULT)
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return dict(UPGRADE_STATUS_DEFAULT)
    merged = dict(UPGRADE_STATUS_DEFAULT)
    merged.update(payload)
    return merged


def write_upgrade_status(data_dir: Path, payload: dict[str, Any]) -> None:
    status_path = data_dir / "state" / "upgrade_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = status_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(status_path)


def set_upgrade_status(
    data_dir: Path,
    status: str,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    payload = read_upgrade_status(data_dir)
    now = _utc_now()
    if status == "running":
        payload.update(
            {
                "status": "running",
                "started_at": now,
                "finished_at": None,
                "last_error": None,
            }
        )
    elif status == "failed":
        payload.update(
            {
                "status": "failed",
                "finished_at": now,
                "last_error": error,
                "started_at": payload.get("started_at") or now,
            }
        )
    elif status == "done":
        payload.update(
            {
                "status": "done",
                "finished_at": now,
                "last_error": None,
                "started_at": payload.get("started_at") or now,
            }
        )
    else:
        payload = dict(UPGRADE_STATUS_DEFAULT)
    write_upgrade_status(data_dir, payload)
    return payload


def plan_upgrades(
    desired: dict[str, Any],
    installed: dict[str, Any],
    platform_key: str,
    *,
    with_redis: bool,
    redis_url: str | None,
    redis_flavor: str,
    centrifugo_override: str | None,
) -> list[UpgradeAction]:
    actions: list[UpgradeAction] = []
    centrifugo_version = get_default_version(desired, "centrifugo")
    centrifugo_state = installed.get("tools", {}).get("centrifugo")
    if not centrifugo_override and not _is_installed(
        centrifugo_state,
        centrifugo_version,
    ):
        asset = get_asset(desired, "centrifugo", platform_key)
        actions.append(
            UpgradeAction(
                tool="centrifugo",
                version=centrifugo_version,
                asset_url=asset["url"],
                asset_sha256=asset["sha256"],
            )
        )

    redis_mode = resolve_redis_mode(with_redis, redis_url, os.name == "nt")
    if redis_mode == "embedded":
        redis_version = get_default_version(desired, "redis_windows")
        redis_state = installed.get("tools", {}).get("redis")
        if not _is_installed(redis_state, redis_version):
            redis_key = f"windows_amd64_{redis_flavor}"
            asset = get_asset(desired, "redis_windows", redis_key)
            actions.append(
                UpgradeAction(
                    tool="redis",
                    version=redis_version,
                    asset_url=asset["url"],
                    asset_sha256=asset["sha256"],
                )
            )

    return actions


def apply_upgrades(
    actions: Iterable[UpgradeAction],
    data_dir: Path,
    installed: dict[str, Any],
    desired: dict[str, Any],
    *,
    with_redis: bool,
    redis_url: str | None,
    redis_flavor: str,
    centrifugo_override: str | None,
    keep_versions: int = DEFAULT_KEEP_VERSIONS,
) -> dict[str, Any]:
    ensure_data_layout(data_dir)
    tools_state = dict(installed.get("tools", {}))

    for action in actions:
        if action.tool == "centrifugo":
            before_version = (tools_state.get("centrifugo") or {}).get("version")
            path = ensure_centrifugo_binary(action.version, data_dir)
            tools_state["centrifugo"] = {
                "version": action.version,
                "path": str(path),
                "sha256": action.asset_sha256,
                "installed_at": _utc_now(),
            }
            log_upgrade(
                data_dir,
                action="infra.install",
                outcome="success",
                tool="centrifugo",
                before_version=before_version,
                after_version=action.version,
                detail=str(path),
            )
        elif action.tool == "redis":
            before_version = (tools_state.get("redis") or {}).get("version")
            server_path, _cli_path = ensure_redis_binary(
                action.version,
                redis_flavor,
                data_dir,
            )
            tools_state["redis"] = {
                "version": action.version,
                "path": str(server_path),
                "sha256": action.asset_sha256,
                "installed_at": _utc_now(),
                "enabled": True,
            }
            log_upgrade(
                data_dir,
                action="infra.install",
                outcome="success",
                tool="redis",
                before_version=before_version,
                after_version=action.version,
                detail=str(server_path),
            )

    if centrifugo_override:
        before_version = (tools_state.get("centrifugo") or {}).get("version")
        tools_state["centrifugo"] = {
            "version": "override",
            "path": centrifugo_override,
            "sha256": "",
            "installed_at": _utc_now(),
        }
        log_upgrade(
            data_dir,
            action="infra.override",
            outcome="success",
            tool="centrifugo",
            before_version=before_version,
            after_version="override",
            detail=centrifugo_override,
        )

    redis_mode = resolve_redis_mode(with_redis, redis_url, os.name == "nt")
    if redis_mode == "disabled":
        redis_state = dict(tools_state.get("redis", {}))
        redis_state["enabled"] = False
        tools_state["redis"] = redis_state
    elif redis_mode == "external":
        tools_state["redis"] = {
            "enabled": True,
            "mode": "external",
            "url": redis_url,
            "installed_at": _utc_now(),
        }
    elif redis_mode == "embedded":
        redis_state = dict(tools_state.get("redis", {}))
        redis_state["enabled"] = True
        tools_state["redis"] = redis_state

    cleanup_versions(data_dir, "centrifugo", keep_versions)
    cleanup_versions(data_dir, "redis", keep_versions)

    updated = dict(installed)
    updated["tools"] = tools_state
    write_installed_state(data_dir, updated)
    return updated


def cleanup_versions(data_dir: Path, tool: str, keep_versions: int) -> None:
    _cleanup_versions(data_dir, tool, keep_versions)


def update_db_state(installed: dict[str, Any], database_url: str) -> dict[str, Any]:
    db_state = dict(installed.get("db", {}))
    db_state["url"] = database_url
    db_state["dialect"] = _db_dialect(database_url)
    db_state["alembic_head"] = read_alembic_revision(database_url)
    installed["db"] = db_state
    return installed


def read_alembic_revision(database_url: str) -> str | None:
    return asyncio.run(_read_alembic_revision(database_url))


def log_upgrade(
    data_dir: Path,
    *,
    action: str,
    outcome: str,
    actor_principal_id: str | None = None,
    tool: str | None = None,
    before_version: str | None = None,
    after_version: str | None = None,
    detail: str | None = None,
) -> None:
    _log_upgrade(
        data_dir,
        action=action,
        outcome=outcome,
        actor_principal_id=actor_principal_id,
        tool=tool,
        before_version=before_version,
        after_version=after_version,
        detail=detail,
    )


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("win"):
        os_name = "windows"
    elif system == "darwin":
        os_name = "darwin"
    elif system == "linux":
        os_name = "linux"
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")

    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        raise RuntimeError(f"Unsupported architecture: {platform.machine()}")

    return f"{os_name}_{arch}"


def _is_installed(state: dict[str, Any] | None, desired_version: str) -> bool:
    if not state:
        return False
    if state.get("version") != desired_version:
        return False
    path = state.get("path")
    return bool(path and Path(path).exists())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_dialect(database_url: str) -> str:
    try:
        return make_url(database_url).get_backend_name()
    except Exception:
        return "unknown"


async def _read_alembic_revision(database_url: str) -> str | None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_read_alembic_revision_sync)
    finally:
        await engine.dispose()


def _read_alembic_revision_sync(connection) -> str | None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return None
    result = connection.execute(text("SELECT version_num FROM alembic_version"))
    row = result.first()
    return row[0] if row else None


def _log_upgrade(
    data_dir: Path,
    *,
    action: str,
    outcome: str,
    actor_principal_id: str | None,
    tool: str | None,
    before_version: str | None,
    after_version: str | None,
    detail: str | None,
) -> None:
    log_path = data_dir / "state" / "upgrade.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": _utc_now(),
        "action": action,
        "outcome": outcome,
        "actor_principal_id": actor_principal_id,
        "tool": tool,
        "before_version": before_version,
        "after_version": after_version,
        "detail": detail,
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _cleanup_versions(data_dir: Path, tool: str, keep_versions: int) -> None:
    tool_dir = data_dir / "bin" / tool
    if not tool_dir.exists():
        return
    versions = [path for path in tool_dir.iterdir() if path.is_dir()]
    if len(versions) <= keep_versions:
        return
    versions_sorted = sorted(versions, key=lambda p: _version_key(p.name))
    for path in versions_sorted[:-keep_versions]:
        shutil.rmtree(path, ignore_errors=True)


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in version.split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(0)
    return tuple(parts)


def _acquire_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("OptAIC is already running (lockfile held).") from exc
    else:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("OptAIC is already running (lockfile held).") from exc


def _release_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
