from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import signal
import subprocess
import urllib.request
import asyncio
import sys

from packaging.version import Version

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import typer

from .config import Settings
from .paths import resolve_data_dir
from .runtime.channel import resolve_channel, resolve_package_index_url
from .runtime.database import resolve_database_url
from .runtime.init_demo import seed_demo
from .runtime.migrate import migration_paths, run_migrations
from .runtime.redis_manager import check_redis, resolve_redis_mode
from .runtime.supervisor import SupervisorConfig, run_supervisor
from .runtime.runtime_config import load_runtime_config
from .runtime.upgrade_manager import (
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
    read_upgrade_status,
    set_upgrade_status,
    update_db_state,
    write_installed_state,
)
from .runtime.package_update import (
    check_pypi_latest,
    download_wheel,
    download_wheel_from_index,
    list_available_versions,
    prepare_upgrade_job,
    write_package_update_state,
)
from .version import get_version

app = typer.Typer(
    add_completion=False, no_args_is_help=True, invoke_without_command=True
)


@dataclass(frozen=True)
class AppContext:
    data_dir: Path


class RedisFlavor(str, Enum):
    msys2 = "msys2"
    cygwin = "cygwin"


class ReleaseChannel(str, Enum):
    prod = "prod"
    uat = "uat"
    staging = "staging"


class RollbackTool(str, Enum):
    centrifugo = "centrifugo"
    redis = "redis"


def _get_data_dir(ctx: typer.Context) -> Path:
    if ctx.obj and isinstance(ctx.obj, AppContext):
        return ctx.obj.data_dir
    return resolve_data_dir()


@app.callback()
def _main(
    ctx: typer.Context,
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        help="Override the OptAIC data directory (or set OPTAIC_DATA_DIR).",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the OptAIC version and exit.",
        is_eager=True,
    ),
) -> None:
    if version:
        typer.echo(get_version())
        raise typer.Exit()
    runtime_config = load_runtime_config(data_dir=data_dir)
    ctx.obj = AppContext(data_dir=runtime_config.data_dir)


@app.command()
def server(
    ctx: typer.Context,
    host: str | None = typer.Option(
        None,
        "--host",
        help="Host interface for the API server.",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="Port for the API server.",
    ),
    no_worker: bool = typer.Option(
        False,
        "--no-worker",
        help="Disable the background worker process.",
    ),
    no_agent: bool = typer.Option(
        False,
        "--no-agent",
        help="Disable the agent process.",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open-browser",
        help="Open the Web UI in a browser after startup.",
    ),
    with_redis: bool | None = typer.Option(
        None,
        "--with-redis",
        help="Enable Redis for Centrifugo (embedded on Windows or external).",
        is_flag=True,
    ),
    redis_url: str | None = typer.Option(
        None,
        "--redis-url",
        help="Use an external Redis URL instead of embedded Redis.",
    ),
    redis_port: int | None = typer.Option(
        None,
        "--redis-port",
        help="Redis port for embedded or external Redis.",
    ),
    redis_bind: str | None = typer.Option(
        None,
        "--redis-bind",
        help="Bind address for embedded Redis.",
    ),
    redis_version: str | None = typer.Option(
        None,
        "--redis-version",
        help="Pinned Redis version for Windows auto-download.",
    ),
    redis_flavor: RedisFlavor | None = typer.Option(
        None,
        "--redis-flavor",
        help="Redis Windows build flavor (msys2 or cygwin).",
    ),
    with_prefect: bool | None = typer.Option(
        None,
        "--with-prefect",
        help="Enable Prefect orchestration (local server by default).",
        is_flag=True,
    ),
    with_mlflow: bool | None = typer.Option(
        None,
        "--with-mlflow",
        help="Enable MLflow tracking/registry (local server by default).",
        is_flag=True,
    ),
) -> None:
    data_dir = _get_data_dir(ctx)
    settings = Settings()
    runtime_config = load_runtime_config(data_dir=data_dir)
    os.environ.setdefault("OPTAIC_DATA_DIR", str(data_dir))
    api_host = host or settings.api_host
    api_port = port or settings.api_port
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = resolve_database_url(settings, data_dir)
    resolved_with_redis = with_redis if with_redis is not None else settings.with_redis
    resolved_redis_url = redis_url if redis_url is not None else settings.redis_url
    resolved_redis_port = redis_port if redis_port is not None else settings.redis_port
    resolved_redis_bind = redis_bind if redis_bind is not None else settings.redis_bind
    resolved_redis_version = (
        redis_version if redis_version is not None else settings.redis_version
    )
    resolved_redis_flavor = (
        redis_flavor.value if redis_flavor is not None else settings.redis_flavor
    )
    resolved_with_prefect = (
        with_prefect
        if with_prefect is not None
        else (runtime_config.prefect.enabled or bool(runtime_config.prefect.api_url))
    )
    resolved_with_mlflow = (
        with_mlflow
        if with_mlflow is not None
        else (runtime_config.mlflow.enabled or bool(runtime_config.mlflow.tracking_uri))
    )
    runtime_config.prefect.enabled = resolved_with_prefect
    runtime_config.mlflow.enabled = resolved_with_mlflow

    if not database_url:
        typer.echo("DATABASE_URL is required when MODE=prod.", err=True)
        raise typer.Exit(code=1)

    if database_url.startswith("sqlite"):
        (data_dir / "db").mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("DATABASE_URL", database_url)

    typer.echo(f"Starting OptAIC server (data dir: {data_dir})")

    server_args = _build_server_args(
        data_dir=data_dir,
        host=api_host,
        port=api_port,
        no_worker=no_worker,
        no_agent=no_agent,
        open_browser=open_browser,
        with_redis=resolved_with_redis,
        with_prefect=resolved_with_prefect,
        with_mlflow=resolved_with_mlflow,
        redis_url=resolved_redis_url,
        redis_port=resolved_redis_port,
        redis_bind=resolved_redis_bind,
        redis_version=resolved_redis_version,
        redis_flavor=resolved_redis_flavor,
    )
    _write_server_args(data_dir, server_args)

    webui_index = Path(__file__).resolve().parent / "webui_dist" / "index.html"
    if not webui_index.exists():
        typer.echo(
            "Web UI assets not found. Run `make build` to bundle the UI.",
            err=True,
        )

    if settings.mode == "embedded" and (
        not settings.centrifugo_api_key or not settings.centrifugo_token_secret
    ):
        typer.echo(
            "CENTRIFUGO_API_KEY and CENTRIFUGO_TOKEN_SECRET are required.",
            err=True,
        )
        raise typer.Exit(code=1)

    exit_code = run_supervisor(
        SupervisorConfig(
            data_dir=data_dir,
            settings=settings,
            host=api_host,
            port=api_port,
            database_url=database_url,
            start_worker=not no_worker,
            start_agent=not no_agent,
            open_browser=open_browser,
            with_redis=resolved_with_redis,
            redis_url=resolved_redis_url,
            redis_port=resolved_redis_port,
            redis_bind=resolved_redis_bind,
            redis_version=resolved_redis_version,
            redis_flavor=resolved_redis_flavor,
            prefect=runtime_config.prefect,
            mlflow=runtime_config.mlflow,
        )
    )
    if exit_code:
        raise typer.Exit(code=exit_code)


@app.command("init-demo")
def init_demo(ctx: typer.Context) -> None:
    data_dir = _get_data_dir(ctx)
    settings = Settings()
    database_url = resolve_database_url(settings, data_dir)
    if not database_url:
        typer.echo("DATABASE_URL is required when MODE=prod.", err=True)
        raise typer.Exit(code=1)

    data_dir.mkdir(parents=True, exist_ok=True)
    if database_url.startswith("sqlite"):
        (data_dir / "db").mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("DATABASE_URL", database_url)

    typer.echo("Running database migrations...")
    run_migrations(database_url)
    typer.echo("Seeding demo data...")

    try:
        demo_ids = asyncio.run(seed_demo(database_url))
    except OperationalError as exc:
        if "database is locked" in str(exc).lower():
            typer.echo(
                "Database is locked. Stop OptAIC server/worker processes using "
                "the SQLite database, then retry.",
                err=True,
            )
        raise typer.Exit(code=1) from exc
    typer.echo("Demo initialized.")
    typer.echo(f"  tenant_id: {demo_ids.tenant_id}")
    typer.echo(f"  alice_principal_id: {demo_ids.alice_id}")
    typer.echo(f"  bob_principal_id: {demo_ids.bob_id}")
    typer.echo(f"  root_resource_id: {demo_ids.root_resource_id}")
    typer.echo(f"  agent_principal_id: {demo_ids.agent_id}")


@app.command()
def doctor(ctx: typer.Context) -> None:
    data_dir = _get_data_dir(ctx)
    settings = Settings()
    database_url = resolve_database_url(settings, data_dir)
    resolved_channel = resolve_channel(settings, data_dir)
    resolved_index_url = resolve_package_index_url(settings, data_dir)
    centrifugo_url = os.environ.get(
        "CENTRIFUGO_URL", f"http://127.0.0.1:{settings.centrifugo_port}"
    )
    typer.echo("Resolved paths:")
    typer.echo(f"  data_dir: {data_dir}")
    typer.echo("Config:")
    typer.echo(f"  mode: {settings.mode}")
    typer.echo(f"  database_url: {database_url or '<missing>'}")
    typer.echo(f"  with_redis: {settings.with_redis}")
    typer.echo(f"  redis_url: {settings.redis_url}")
    typer.echo(f"  redis_bind: {settings.redis_bind}")
    typer.echo(f"  redis_port: {settings.redis_port}")
    typer.echo(f"  redis_version: {settings.redis_version}")
    typer.echo(f"  redis_flavor: {settings.redis_flavor}")
    typer.echo(f"  package_index_url: {settings.package_index_url}")
    typer.echo(f"  channel: {resolved_channel}")
    typer.echo(f"  artifactory_base_url: {settings.artifactory_base_url}")
    typer.echo(f"  resolved_index_url: {resolved_index_url}")
    typer.echo(f"  package_extra_index_url: {settings.package_extra_index_url}")
    typer.echo(f"  package_trusted_host: {settings.package_trusted_host}")
    typer.echo(f"  package_name: {settings.package_name}")
    typer.echo(f"  centrifugo_port: {settings.centrifugo_port}")
    typer.echo(f"  centrifugo_api_key: {settings.centrifugo_api_key}")
    typer.echo(f"  centrifugo_token_secret: {settings.centrifugo_token_secret}")
    typer.echo(f"  api_host: {settings.api_host}")
    typer.echo(f"  api_port: {settings.api_port}")
    db_status, schema_status = _check_database(database_url)
    typer.echo(f"  db_connectivity: {db_status}")
    typer.echo(f"  db_schema: {schema_status}")
    redis_status, centrifugo_engine = _check_redis(settings)
    typer.echo(f"  redis: {redis_status}")
    typer.echo(f"  centrifugo_engine: {centrifugo_engine}")
    centrifugo_status = _check_centrifugo(centrifugo_url)
    typer.echo(f"  centrifugo_health: {centrifugo_status}")


@app.command()
def upgrade(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show planned upgrades without applying them.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply database and infrastructure upgrades.",
    ),
    restart: bool = typer.Option(
        False,
        "--restart",
        help="Restart services after applying upgrades (manual by default).",
    ),
    self_upgrade: bool = typer.Option(
        False,
        "--self",
        help="Run a self-upgrade using a detached upgrader process.",
    ),
    with_redis: bool | None = typer.Option(
        None,
        "--with-redis",
        help="Enable Redis upgrades when running embedded Redis on Windows.",
        is_flag=True,
    ),
    cleanup_old_versions: int = typer.Option(
        2,
        "--cleanup-old-versions",
        help="Number of tool versions to retain after upgrade.",
    ),
    check_package_updates: bool = typer.Option(
        False,
        "--check-package-updates",
        "--check",
        help="Check for package updates (optional).",
    ),
    channel: ReleaseChannel | None = typer.Option(
        None,
        "--channel",
        help="Upgrade channel for package updates (staging, uat, prod).",
    ),
) -> None:
    if self_upgrade and not restart:
        typer.echo("--self requires --restart.", err=True)
        raise typer.Exit(code=1)
    if restart and not apply:
        typer.echo("--restart requires --apply.", err=True)
        raise typer.Exit(code=1)
    if not dry_run and not apply:
        dry_run = True

    data_dir = _get_data_dir(ctx)
    settings = Settings()
    runtime_config = load_runtime_config(data_dir=data_dir)
    resolved_channel = resolve_channel(
        settings,
        data_dir,
        channel.value if channel is not None else None,
    )
    resolved_index_url = resolve_package_index_url(
        settings,
        data_dir,
        channel=resolved_channel,
    )
    database_url = resolve_database_url(settings, data_dir)
    if not database_url:
        typer.echo("DATABASE_URL is required when MODE=prod.", err=True)
        raise typer.Exit(code=1)

    if apply:
        status = read_upgrade_status(data_dir)
        if status.get("status") == "running":
            typer.echo(
                "Another upgrade is already running; try again later.",
                err=True,
            )
            raise typer.Exit(code=1)

    resolved_with_redis = with_redis if with_redis is not None else settings.with_redis
    resolved_redis_url = settings.redis_url
    resolved_redis_flavor = settings.redis_flavor
    resolved_with_prefect = runtime_config.prefect.enabled or bool(
        runtime_config.prefect.api_url
    )
    resolved_with_mlflow = runtime_config.mlflow.enabled or bool(
        runtime_config.mlflow.tracking_uri
    )

    package_update = None
    wheel_path = None
    latest_version = None
    if check_package_updates:
        try:
            current_version = get_version()
            if resolved_index_url:
                versions = list_available_versions(
                    resolved_index_url,
                    settings.package_name,
                )
                latest_version = str(versions[-1]) if versions else current_version
                package_update = {
                    "package": settings.package_name,
                    "current_version": current_version,
                    "latest_version": latest_version,
                    "has_update": _is_newer_version(latest_version, current_version),
                    "source": "index",
                    "index_url": resolved_index_url,
                    "checked_at": _utc_now(),
                }
            else:
                typer.echo(
                    "OPTAIC_PACKAGE_INDEX_URL or OPTAIC_ARTIFACTORY_BASE_URL is not set; "
                    "checking public PyPI.",
                )
                package_update = check_pypi_latest(
                    package_name=settings.package_name,
                    current_version=current_version,
                )
            write_package_update_state(data_dir, package_update)
            _print_package_update(package_update)
            latest_version = str(package_update.get("latest_version"))
        except Exception as exc:
            typer.echo(f"Package update check failed: {exc}", err=True)

    desired_manifest = load_desired_manifest()
    installed_state = load_installed_state(data_dir)
    centrifugo_override = os.environ.get("OPTAIC_CENTRIFUGO_PATH")
    try:
        actions = plan_upgrades(
            desired_manifest,
            installed_state,
            platform_key(),
            with_redis=resolved_with_redis,
            redis_url=resolved_redis_url,
            redis_flavor=resolved_redis_flavor,
            centrifugo_override=centrifugo_override,
        )
    except Exception as exc:
        if (
            resolved_with_redis
            and not sys.platform.startswith("win")
            and not resolved_redis_url
        ):
            typer.echo(
                "Redis is enabled without --redis-url. Provide --redis-url or "
                "disable --with-redis on non-Windows.",
                err=True,
            )
        typer.echo(f"Failed to plan upgrades: {exc}", err=True)
        raise typer.Exit(code=1)

    if dry_run:
        _print_upgrade_plan(actions)
        return

    ensure_data_layout(data_dir)
    lock = acquire_lock(data_dir)
    upgrade_success = False
    before_rev: str | None = None
    after_rev: str | None = None
    try:
        set_upgrade_status(data_dir, "running")
        before_rev = read_alembic_revision(database_url)
        typer.echo("Running database migrations...")
        try:
            migrate_db(database_url)
            after_rev = read_alembic_revision(database_url)
            log_upgrade(
                data_dir,
                action="db.migrate",
                outcome="success",
                before_version=before_rev,
                after_version=after_rev,
            )
        except Exception as exc:
            log_upgrade(
                data_dir,
                action="db.migrate",
                outcome="failed",
                before_version=before_rev,
                after_version=None,
                detail=str(exc),
            )
            raise
        if actions:
            typer.echo("Applying infrastructure upgrades...")
        installed_state = apply_upgrades(
            actions,
            data_dir,
            installed_state,
            desired_manifest,
            with_redis=resolved_with_redis,
            redis_url=resolved_redis_url,
            redis_flavor=resolved_redis_flavor,
            centrifugo_override=centrifugo_override,
            keep_versions=cleanup_old_versions,
        )
        installed_state = update_db_state(installed_state, database_url)
        write_installed_state(data_dir, installed_state)
        if (
            check_package_updates
            and package_update
            and package_update.get("has_update")
        ):
            latest_version = str(package_update.get("latest_version"))
            downloads_dir = (
                data_dir / "downloads" / settings.package_name / latest_version
            )
            if resolved_index_url:
                wheel_path = download_wheel_from_index(
                    resolved_index_url,
                    settings.package_name,
                    latest_version,
                    downloads_dir,
                )
            else:
                wheel_path = download_wheel(
                    latest_version,
                    downloads_dir,
                    package_name=settings.package_name,
                )
            job_path = prepare_upgrade_job(
                data_dir,
                package_name=settings.package_name,
                version=latest_version,
                wheel_path=wheel_path,
                index_url=resolved_index_url,
                extra_index_url=settings.package_extra_index_url,
                trusted_host=settings.package_trusted_host,
            )
            typer.echo(f"Cached OptAIC wheel at {wheel_path}")
            typer.echo(f"Prepared upgrade job at {job_path}")
        typer.echo("Upgrade complete.")
        upgrade_success = True
        set_upgrade_status(data_dir, "done")
    except Exception as exc:
        set_upgrade_status(data_dir, "failed", error=str(exc))
        log_upgrade(
            data_dir,
            action="upgrade.failed",
            outcome="failed",
            before_version=before_rev,
            after_version=after_rev,
            detail=str(exc),
        )
        raise
    finally:
        lock.release()

    if self_upgrade:
        if not check_package_updates:
            typer.echo("--self requires --check-package-updates.", err=True)
            raise typer.Exit(code=1)
        if package_update and not package_update.get("has_update"):
            typer.echo("No package update available for self-upgrade.", err=True)
            raise typer.Exit(code=1)
        if not latest_version:
            typer.echo("No package update found for self-upgrade.", err=True)
            raise typer.Exit(code=1)
        if not resolved_index_url:
            typer.echo(
                "Self-upgrade requires OPTAIC_PACKAGE_INDEX_URL or "
                "OPTAIC_ARTIFACTORY_BASE_URL to be set.",
                err=True,
            )
            raise typer.Exit(code=1)
        server_pid = _read_server_pid(data_dir)
        server_args = _load_server_args(
            data_dir,
            resolved_with_redis,
            resolved_with_prefect,
            resolved_with_mlflow,
        )
        job_path = _write_self_upgrade_job(
            data_dir,
            package_name=settings.package_name,
            current_version=get_version(),
            version=latest_version,
            wheel_path=wheel_path,
            server_args=server_args,
            server_pid=server_pid,
            index_url=resolved_index_url,
            extra_index_url=settings.package_extra_index_url,
            trusted_host=settings.package_trusted_host,
        )
        _spawn_self_upgrade(job_path, server_pid)
        if server_pid:
            _terminate_server_pid(server_pid)
        raise typer.Exit()

    if restart and upgrade_success:
        typer.echo("Restarting OptAIC server...")
        _restart_server(
            data_dir,
            resolved_with_redis,
            resolved_with_prefect,
            resolved_with_mlflow,
        )


@app.command()
def rollback(
    ctx: typer.Context,
    tool: RollbackTool = typer.Option(
        ...,
        "--tool",
        help="Tool to roll back (centrifugo or redis).",
    ),
    to_version: str = typer.Option(
        ...,
        "--to-version",
        help="Version to roll back to.",
    ),
    restart: bool = typer.Option(
        False,
        "--restart",
        help="Restart services after rollback.",
    ),
) -> None:
    data_dir = _get_data_dir(ctx)
    version_dir = _resolve_tool_dir(data_dir, tool, to_version)
    if not version_dir.exists():
        typer.echo(
            f"Version not found: {version_dir}",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        binary_path = _resolve_tool_binary(tool, version_dir)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    lock = acquire_lock(data_dir)
    try:
        installed_state = load_installed_state(data_dir)
        tools_state = dict(installed_state.get("tools", {}))
        tool_state = dict(tools_state.get(tool.value, {}))
        before_version = tool_state.get("version")
        tool_state["version"] = to_version
        tool_state["path"] = str(binary_path)
        tool_state["installed_at"] = _utc_now()
        if tool.value == "redis":
            tool_state.setdefault("enabled", True)
        tools_state[tool.value] = tool_state
        installed_state["tools"] = tools_state
        write_installed_state(data_dir, installed_state)
        log_upgrade(
            data_dir,
            action="rollback",
            outcome="success",
            tool=tool.value,
            before_version=before_version,
            after_version=to_version,
        )
        typer.echo(f"Rolled back {tool.value} to {to_version}.")
    finally:
        lock.release()

    if restart:
        settings = Settings()
        runtime_config = load_runtime_config(data_dir=data_dir)
        typer.echo("Restarting OptAIC server...")
        _restart_server(
            data_dir,
            settings.with_redis,
            runtime_config.prefect.enabled or bool(runtime_config.prefect.api_url),
            runtime_config.mlflow.enabled or bool(runtime_config.mlflow.tracking_uri),
        )


@app.command()
def version() -> None:
    typer.echo(get_version())


def _check_centrifugo(base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                return "ok"
            return f"status={response.status}"
    except Exception as exc:
        return f"error: {exc}"


def _check_redis(settings: Settings) -> tuple[str, str]:
    try:
        resolved = resolve_redis_mode(
            settings.with_redis,
            settings.redis_url,
            sys.platform.startswith("win"),
        )
    except Exception as exc:
        return f"error: {exc}", "unknown"
    if resolved == "disabled":
        return "disabled", "memory"
    redis_url = (
        settings.redis_url or f"redis://{settings.redis_bind}:{settings.redis_port}/0"
    )
    status, version = check_redis(redis_url)
    if status != "ok":
        return status, "redis"
    if version:
        return f"ok (redis {version}, {resolved})", "redis"
    return f"ok ({resolved})", "redis"


def _check_database(database_url: str | None) -> tuple[str, str]:
    if not database_url:
        return "error: DATABASE_URL is required", "unknown"
    try:
        return asyncio.run(_check_database_async(database_url))
    except Exception as exc:
        return f"error: {exc}", "unknown"


async def _check_database_async(database_url: str) -> tuple[str, str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            current_rev = await conn.run_sync(_read_alembic_revision)
    finally:
        await engine.dispose()

    heads = _alembic_heads()
    if not current_rev:
        schema_status = "missing"
    elif current_rev in heads:
        schema_status = "ok"
    else:
        schema_status = f"stale (db={current_rev}, head={','.join(heads)})"
    return "ok", schema_status


def _print_upgrade_plan(actions) -> None:
    if not actions:
        typer.echo("No upgrades required.")
        return
    typer.echo("Planned upgrades:")
    for action in actions:
        typer.echo(f"  - {action.tool}: {action.version}")


def _print_package_update(result: dict[str, object]) -> None:
    package = result.get("package", "optaic")
    current = result.get("current_version", "unknown")
    latest = result.get("latest_version", "unknown")
    has_update = result.get("has_update", False)
    if has_update:
        typer.echo(f"Update available for {package}: {current} -> {latest}")
    else:
        typer.echo(f"{package} is up to date ({current}).")


def _is_newer_version(latest: str, current: str) -> bool:
    try:
        return Version(latest) > Version(current)
    except Exception:
        return latest != current


def _build_server_args(
    *,
    data_dir: Path,
    host: str,
    port: int,
    no_worker: bool,
    no_agent: bool,
    open_browser: bool,
    with_redis: bool,
    with_prefect: bool,
    with_mlflow: bool,
    redis_url: str | None,
    redis_port: int,
    redis_bind: str,
    redis_version: str,
    redis_flavor: str,
) -> list[str]:
    args = ["--data-dir", str(data_dir), "server", "--host", host, "--port", str(port)]
    if no_worker:
        args.append("--no-worker")
    if no_agent:
        args.append("--no-agent")
    if open_browser:
        args.append("--open-browser")
    if with_prefect:
        args.append("--with-prefect")
    if with_mlflow:
        args.append("--with-mlflow")
    if with_redis:
        args.append("--with-redis")
        if redis_url:
            args.extend(["--redis-url", redis_url])
        args.extend(
            [
                "--redis-port",
                str(redis_port),
                "--redis-bind",
                redis_bind,
                "--redis-version",
                redis_version,
                "--redis-flavor",
                redis_flavor,
            ]
        )
    return args


def _write_server_args(data_dir: Path, args: list[str]) -> Path:
    state_path = data_dir / "state" / "server_args.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"args": args, "saved_at": _utc_now()}
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return state_path


def _load_server_args(
    data_dir: Path,
    with_redis: bool,
    with_prefect: bool,
    with_mlflow: bool,
) -> list[str]:
    state_path = data_dir / "state" / "server_args.json"
    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            args = payload.get("args")
            if isinstance(args, list) and args:
                return [str(item) for item in args]
        except Exception:
            pass
    args = ["--data-dir", str(data_dir), "server"]
    if with_prefect:
        args.append("--with-prefect")
    if with_mlflow:
        args.append("--with-mlflow")
    if with_redis:
        args.append("--with-redis")
    return args


def _read_server_pid(data_dir: Path) -> int | None:
    pid_path = data_dir / "state" / "server.pid"
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _write_self_upgrade_job(
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
) -> Path:
    job_path = data_dir / "state" / "upgrade_job.json"
    job_path.parent.mkdir(parents=True, exist_ok=True)
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
    }
    job_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return job_path


def _spawn_self_upgrade(job_path: Path, server_pid: int | None) -> None:
    cmd = [
        sys.executable,
        "-m",
        "optaic.runtime.self_upgrade",
        "--job",
        str(job_path),
    ]
    if server_pid:
        cmd.extend(["--wait-pid", str(server_pid)])
    creationflags = 0
    start_new_session = False
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        start_new_session = True
    subprocess.Popen(
        cmd, creationflags=creationflags, start_new_session=start_new_session
    )


def _terminate_server_pid(server_pid: int) -> None:
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/PID", str(server_pid), "/T"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(server_pid, signal.SIGTERM)
    except Exception:
        return


def _resolve_tool_dir(data_dir: Path, tool: RollbackTool, version: str) -> Path:
    return data_dir / "bin" / tool.value / version


def _resolve_tool_binary(tool: RollbackTool, version_dir: Path) -> Path:
    if tool == RollbackTool.centrifugo:
        name = "centrifugo.exe" if sys.platform.startswith("win") else "centrifugo"
    else:
        name = "redis-server.exe" if sys.platform.startswith("win") else "redis-server"
    for candidate in version_dir.rglob(name):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{tool.value} binary not found in {version_dir}")


def _restart_server(
    data_dir: Path,
    with_redis: bool,
    with_prefect: bool,
    with_mlflow: bool,
) -> None:
    args = _load_server_args(data_dir, with_redis, with_prefect, with_mlflow)
    cmd = [sys.executable, "-m", "optaic.cli"] + list(args)
    env = os.environ.copy()
    env["OPTAIC_DATA_DIR"] = str(data_dir)
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(cmd, env=env, creationflags=creationflags)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_alembic_revision(connection) -> str | None:
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
