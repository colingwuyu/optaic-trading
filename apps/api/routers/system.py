from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from packaging.version import Version
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db, reset_session
from apps.api.schemas import (
    SystemChannelStatus,
    SystemChannelUpdate,
    SystemConfig,
    SystemInfraAction,
    SystemPackageUpdate,
    SystemRuntimeStatus,
    SystemUpgradePlan,
    SystemUpgradePlanIn,
    SystemUpgradeStart,
    SystemUpgradeStartIn,
)
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac import authorize
from libs.core.rbac.models import ActorContext
from libs.db.models.rbac import RoleBinding
from libs.db.models.resource import Resource
from optaic.config import Settings as OptaicSettings
from optaic.paths import resolve_data_dir
from optaic.runtime.channel import (
    resolve_channel,
    resolve_package_index_url,
    write_channel_state,
)
from optaic.runtime.database import resolve_database_url
from optaic.runtime.migrate import migration_paths
from optaic.runtime.package_update import (
    check_pypi_latest,
    download_wheel_from_index,
    list_available_versions,
    write_package_update_state,
)
from optaic.runtime.runtime_config import load_runtime_config
from optaic.runtime.upgrade_manager import (
    load_desired_manifest,
    load_installed_state,
    log_upgrade,
    plan_upgrades,
    platform_key,
    read_upgrade_status,
    set_upgrade_status,
)
from optaic.version import get_version

router = APIRouter(prefix="/system", tags=["System"])

_OWNER_ROLES = {"owner", "delegator"}


@router.get("/runtime", response_model=SystemRuntimeStatus)
async def system_runtime(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SystemRuntimeStatus:
    _ = await _require_system_admin(db, actor)
    settings = OptaicSettings()
    data_dir = resolve_data_dir()
    resolved_channel = resolve_channel(settings, data_dir)
    resolved_index_url = resolve_package_index_url(
        settings,
        data_dir,
        channel=resolved_channel,
    )
    database_url = resolve_database_url(settings, data_dir)
    db_dialect = _db_dialect(database_url) if database_url else None
    try:
        alembic_head = await db.run_sync(_read_alembic_revision_sync)
    except Exception:
        alembic_head = None
    installed_state = load_installed_state(data_dir)
    tools = dict(installed_state.get("tools", {}))
    resolved_redis_url = os.environ.get("REDIS_URL") or settings.redis_url
    centrifugo_engine = "redis" if resolved_redis_url else "memory"
    server_args = _read_server_args_file(data_dir)
    if server_args is None:
        with_redis = bool(settings.with_redis or resolved_redis_url)
    else:
        with_redis = "--with-redis" in server_args
    upgrade_status = read_upgrade_status(data_dir)
    last_upgrade = upgrade_status.get("finished_at") or _read_last_upgrade_time(
        data_dir
    )

    return SystemRuntimeStatus(
        version=get_version(),
        channel=resolved_channel,
        package_index_url=resolved_index_url,
        db_dialect=db_dialect,
        db_alembic_head=alembic_head,
        tools=tools,
        centrifugo_engine=centrifugo_engine,
        with_redis=with_redis,
        last_upgrade_at=last_upgrade,
        upgrade_status=upgrade_status,
    )


@router.get("/config", response_model=SystemConfig)
async def system_config(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SystemConfig:
    _ = await _require_system_admin(db, actor)
    runtime_config = load_runtime_config()
    return SystemConfig(**runtime_config.as_dict(redact=True))


@router.get("/channel", response_model=SystemChannelStatus)
async def system_channel(
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SystemChannelStatus:
    _ = await _require_system_admin(db, actor)
    settings = OptaicSettings()
    data_dir = resolve_data_dir()
    resolved_channel = resolve_channel(settings, data_dir)
    resolved_index_url = resolve_package_index_url(
        settings,
        data_dir,
        channel=resolved_channel,
    )
    return SystemChannelStatus(
        channel=resolved_channel,
        package_index_url=resolved_index_url,
    )


@router.post("/channel", response_model=SystemChannelStatus)
async def system_channel_update(
    payload: SystemChannelUpdate,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SystemChannelStatus:
    system_space = await _require_system_admin(db, actor)
    settings = OptaicSettings()
    data_dir = resolve_data_dir()
    write_channel_state(data_dir, payload.channel, actor_principal_id=str(actor.id))
    resolved_index_url = resolve_package_index_url(
        settings,
        data_dir,
        channel=payload.channel,
    )
    await _record_system_activity(
        db,
        actor,
        system_space,
        action="system.channel_set",
        payload={"channel": payload.channel},
    )
    return SystemChannelStatus(
        channel=payload.channel,
        package_index_url=resolved_index_url,
    )


@router.post("/upgrade/plan", response_model=SystemUpgradePlan)
async def upgrade_plan(
    payload: SystemUpgradePlanIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SystemUpgradePlan:
    system_space = await _require_system_admin(db, actor)
    settings = OptaicSettings()
    data_dir = resolve_data_dir()
    resolved_channel = resolve_channel(settings, data_dir)
    resolved_index_url = resolve_package_index_url(
        settings,
        data_dir,
        channel=resolved_channel,
    )
    warnings: list[str] = []

    package_update = None
    if payload.check_package_updates:
        try:
            package_update = _check_package_updates(
                settings,
                data_dir,
                warnings,
                resolved_index_url=resolved_index_url,
            )
        except Exception as exc:
            warnings.append(f"Package update check failed: {exc}")

    infra_actions: list[SystemInfraAction] = []
    desired_manifest = load_desired_manifest()
    installed_state = load_installed_state(data_dir)
    centrifugo_override = os.environ.get("OPTAIC_CENTRIFUGO_PATH")
    try:
        actions = plan_upgrades(
            desired_manifest,
            installed_state,
            platform_key(),
            with_redis=payload.with_redis,
            redis_url=settings.redis_url,
            redis_flavor=settings.redis_flavor,
            centrifugo_override=centrifugo_override,
        )
        infra_actions = [
            SystemInfraAction(
                tool=action.tool,
                version=action.version,
                asset_url=action.asset_url,
                asset_sha256=action.asset_sha256,
            )
            for action in actions
        ]
    except Exception as exc:
        warnings.append(str(exc))

    db_migration_needed = await _db_migration_needed(db, warnings)

    await _record_system_activity(
        db,
        actor,
        system_space,
        action="system.upgrade_planned",
        payload={
            "with_redis": payload.with_redis,
            "check_package_updates": payload.check_package_updates,
            "infra_actions": [action.model_dump() for action in infra_actions],
            "db_migration_needed": db_migration_needed,
        },
    )

    return SystemUpgradePlan(
        package_update=package_update,
        infra_plan=infra_actions,
        db_migration_needed=db_migration_needed,
        warnings=warnings,
    )


@router.post("/upgrade/start", response_model=SystemUpgradeStart)
async def upgrade_start(
    background_tasks: BackgroundTasks,
    payload: SystemUpgradeStartIn = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SystemUpgradeStart:
    system_space = await _require_system_admin(db, actor)
    settings = OptaicSettings()
    data_dir = resolve_data_dir()
    resolved_channel = resolve_channel(settings, data_dir)
    resolved_index_url = resolve_package_index_url(
        settings,
        data_dir,
        channel=resolved_channel,
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    current_status = read_upgrade_status(data_dir)
    if current_status.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="An upgrade is already running.",
        )

    latest_version = None
    wheel_path = None
    message = None
    skip_install = not payload.apply_package_update
    if payload.apply_package_update:
        if not resolved_index_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "OPTAIC_PACKAGE_INDEX_URL or OPTAIC_ARTIFACTORY_BASE_URL "
                    "is not configured."
                ),
            )
        versions = list_available_versions(
            resolved_index_url,
            settings.package_name,
        )
        if not versions:
            raise HTTPException(status_code=404, detail="No package versions found.")
        latest_version = str(versions[-1])
        current = get_version()
        if Version(latest_version) <= Version(current):
            message = "Already on the latest version."
            return SystemUpgradeStart(
                status="up-to-date",
                will_restart=False,
                message=message,
            )
        downloads_dir = data_dir / "downloads" / settings.package_name / latest_version
        wheel_path = download_wheel_from_index(
            resolved_index_url,
            settings.package_name,
            latest_version,
            downloads_dir,
        )

    server_pid = _read_server_pid(data_dir)
    server_args = _read_server_args_file(data_dir) or ["server"]
    server_args = _apply_with_redis_args(server_args, settings, payload.with_redis)
    job_path = _write_upgrade_job(
        data_dir,
        package_name=settings.package_name,
        current_version=get_version(),
        version=latest_version or get_version(),
        wheel_path=wheel_path,
        server_args=server_args,
        server_pid=server_pid,
        index_url=resolved_index_url,
        extra_index_url=settings.package_extra_index_url,
        trusted_host=settings.package_trusted_host,
        skip_install=skip_install,
        actor_principal_id=str(actor.id),
    )

    will_restart = bool(payload.restart)
    if will_restart and background_tasks is not None:
        background_tasks.add_task(_trigger_self_upgrade, job_path, server_pid)
    set_upgrade_status(data_dir, "running")
    log_upgrade(
        data_dir,
        action="upgrade.requested",
        outcome="scheduled",
        actor_principal_id=str(actor.id),
        before_version=get_version(),
        after_version=latest_version or get_version(),
    )

    await _record_system_activity(
        db,
        actor,
        system_space,
        action="system.upgrade_started",
        payload={
            "with_redis": payload.with_redis,
            "apply_package_update": payload.apply_package_update,
            "restart": payload.restart,
            "job_path": str(job_path),
        },
    )

    return SystemUpgradeStart(
        status="started",
        will_restart=will_restart,
        job_path=str(job_path),
        message=message,
    )


async def _require_system_admin(db: AsyncSession, actor: ActorContext) -> Resource:
    system_space = await _get_system_space(db, actor.tenant_id)
    if await _has_owner_role(db, actor, system_space):
        return system_space
    allowed, _explain = await authorize(
        db,
        actor.tenant_id,
        actor.id,
        system_space.id,
        "ADMIN",
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="System access requires owner/delegator role or ADMIN permission.",
        )
    return system_space


async def _get_system_space(db: AsyncSession, tenant_id) -> Resource:
    result = await db.scalars(
        select(Resource).where(
            Resource.tenant_id == tenant_id,
            Resource.type == "Space",
            Resource.space_kind == "system",
        )
    )
    system_space = result.first()
    if not system_space:
        raise HTTPException(status_code=404, detail="System space not found.")
    return system_space


async def _has_owner_role(
    db: AsyncSession,
    actor: ActorContext,
    system_space: Resource,
) -> bool:
    chain = await _scope_chain(db, actor.tenant_id, system_space)
    scope_ids = [resource.id for resource in chain]
    if not scope_ids:
        return False
    result = await db.scalars(
        select(RoleBinding).where(
            RoleBinding.tenant_id == actor.tenant_id,
            RoleBinding.principal_id == actor.id,
            RoleBinding.scope_resource_id.in_(scope_ids),
            RoleBinding.role_name.in_(_OWNER_ROLES),
            RoleBinding.revoked_at.is_(None),
        )
    )
    return result.first() is not None


async def _scope_chain(
    db: AsyncSession,
    tenant_id,
    start_resource: Resource,
) -> list[Resource]:
    chain: list[Resource] = []
    current = start_resource
    while current:
        chain.append(current)
        metadata = current.metadata_json or {}
        if metadata.get("inherit_break") or metadata.get("break_inheritance"):
            break
        if not current.parent_id:
            break
        result = await db.scalars(
            select(Resource).where(
                Resource.id == current.parent_id,
                Resource.tenant_id == tenant_id,
            )
        )
        parent = result.first()
        if not parent:
            break
        current = parent
    return chain


def _check_package_updates(
    settings: OptaicSettings,
    data_dir: Path,
    warnings: list[str],
    *,
    resolved_index_url: str | None,
) -> SystemPackageUpdate:
    current_version = get_version()
    if resolved_index_url:
        versions = list_available_versions(
            resolved_index_url,
            settings.package_name,
        )
        latest = str(versions[-1]) if versions else current_version
        has_update = Version(latest) > Version(current_version)
        payload = {
            "package": settings.package_name,
            "current_version": current_version,
            "latest_version": latest,
            "has_update": has_update,
            "source": "index",
            "index_url": resolved_index_url,
            "checked_at": _utc_now(),
        }
    else:
        warnings.append(
            "OPTAIC_PACKAGE_INDEX_URL or OPTAIC_ARTIFACTORY_BASE_URL is not configured."
        )
        payload = check_pypi_latest(
            package_name=settings.package_name,
            current_version=current_version,
        )
        payload["message"] = (
            "OPTAIC_PACKAGE_INDEX_URL or OPTAIC_ARTIFACTORY_BASE_URL is not configured."
        )
    write_package_update_state(data_dir, payload)
    return SystemPackageUpdate(**payload)


async def _db_migration_needed(db: AsyncSession, warnings: list[str]) -> bool:
    try:
        current_rev = await db.run_sync(_read_alembic_revision_sync)
        heads = _alembic_heads()
    except Exception as exc:
        warnings.append(f"Failed to inspect migrations: {exc}")
        return True
    if not current_rev:
        return True
    return current_rev not in heads


async def _record_system_activity(
    db: AsyncSession,
    actor: ActorContext,
    system_space: Resource,
    *,
    action: str,
    payload: dict[str, Any],
) -> None:
    resource_id = system_space.id
    resource_type = system_space.type
    await reset_session(db)

    async def _noop(session: AsyncSession) -> None:
        return None

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=resource_id,
        resource_type=resource_type,
        action=action,
        payload=payload,
    )
    await tx_activity(db, envelope, _noop)


def _trigger_self_upgrade(job_path: Path, server_pid: int | None) -> None:
    cmd = [sys.executable, "-m", "optaic.runtime.self_upgrade", "--job", str(job_path)]
    cmd += ["--wait-pid", "0"]
    creationflags = 0
    start_new_session = False
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        start_new_session = True
    subprocess.Popen(
        cmd, creationflags=creationflags, start_new_session=start_new_session
    )
    os._exit(0)


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.kill(pid, 15)


def _write_upgrade_job(
    data_dir: Path,
    *,
    package_name: str,
    current_version: str,
    version: str,
    wheel_path: Path | None,
    server_args: list[str],
    server_pid: int | None,
    index_url: str | None,
    extra_index_url: str | None,
    trusted_host: str | None,
    skip_install: bool,
    actor_principal_id: str | None,
) -> Path:
    job_path = data_dir / "state" / "upgrade_job.json"
    payload = {
        "package": package_name,
        "current_version": current_version,
        "version": version,
        "wheel_path": str(wheel_path) if wheel_path else None,
        "index_url": index_url,
        "extra_index_url": extra_index_url,
        "trusted_host": trusted_host,
        "server_args": server_args,
        "server_pid": server_pid,
        "data_dir": str(data_dir),
        "created_at": _utc_now(),
        "status": "pending",
        "skip_install": skip_install,
        "actor_principal_id": actor_principal_id,
    }
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return job_path


def _read_server_pid(data_dir: Path) -> int | None:
    pid_path = data_dir / "state" / "server.pid"
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _read_server_args_file(data_dir: Path) -> list[str] | None:
    args_path = data_dir / "state" / "server_args.json"
    if not args_path.exists():
        return None
    try:
        payload = json.loads(args_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    args = payload.get("args")
    if isinstance(args, list) and args:
        return [str(item) for item in args]
    return None


def _apply_with_redis_args(
    args: list[str],
    settings: OptaicSettings,
    with_redis: bool,
) -> list[str]:
    if not with_redis:
        return _strip_redis_args(args)
    clean = list(args)
    if "--with-redis" not in clean:
        clean.append("--with-redis")
    if settings.redis_url:
        _ensure_option(clean, "--redis-url", settings.redis_url)
    _ensure_option(clean, "--redis-port", settings.redis_port)
    _ensure_option(clean, "--redis-bind", settings.redis_bind)
    _ensure_option(clean, "--redis-version", settings.redis_version)
    _ensure_option(clean, "--redis-flavor", settings.redis_flavor)
    return clean


def _strip_redis_args(args: list[str]) -> list[str]:
    skip_flags = {
        "--with-redis",
        "--redis-url",
        "--redis-port",
        "--redis-bind",
        "--redis-version",
        "--redis-flavor",
    }
    cleaned: list[str] = []
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg in skip_flags:
            if arg != "--with-redis" and idx + 1 < len(args):
                idx += 2
                continue
            idx += 1
            continue
        cleaned.append(arg)
        idx += 1
    return cleaned


def _ensure_option(args: list[str], flag: str, value: Any) -> None:
    if flag in args:
        return
    args.extend([flag, str(value)])


def _read_last_upgrade_time(data_dir: Path) -> str | None:
    log_path = data_dir / "state" / "upgrade.log"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return None
    if not lines:
        return None
    for raw in reversed(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            ts = payload.get("timestamp")
            if isinstance(ts, str):
                return ts
        except Exception:
            if line.startswith("[") and "]" in line:
                return line.split("]")[0].lstrip("[")
    return None


def _db_dialect(database_url: str) -> str:
    try:
        return make_url(database_url).get_backend_name()
    except Exception:
        return "unknown"


def _read_alembic_revision_sync(connection) -> str | None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return None
    result = connection.execute(text("SELECT version_num FROM alembic_version"))
    row = result.first()
    return row[0] if row else None


def _alembic_heads() -> list[str]:
    with migration_paths() as (config_path, migrations_path, _sys_path_root):
        alembic_cfg = Config(str(config_path))
        alembic_cfg.set_main_option("script_location", str(migrations_path))
        script = ScriptDirectory.from_config(alembic_cfg)
        return script.get_heads()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
