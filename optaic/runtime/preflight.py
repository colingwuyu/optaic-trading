"""
Pre-flight checks and migrations before service startup.

Runs before any services start:
1. Acquire global lock
2. Run OptAIC DB migrations
3. Check engine modes (local/remote)
4. Run engine DB migrations for local engines
5. Release lock and proceed with startup

If migrations fail, startup is aborted with actionable error message.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from optaic.runtime.runtime_config import RuntimeConfig
from optaic.runtime.upgrade_manager import acquire_lock, LockHandle


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PreflightResult:
    """Result of pre-flight checks."""

    success: bool
    prefect_migrated: bool = False
    mlflow_migrated: bool = False
    errors: list[str] | None = None
    backup_paths: dict[str, str] | None = None


def run_preflight(
    config: RuntimeConfig,
    *,
    allow_engine_downgrade: bool = False,
    reset_prefect_db: bool = False,
    reset_mlflow_db: bool = False,
) -> PreflightResult:
    """
    Run pre-flight checks and migrations.

    This should be called before starting any services.

    Args:
        config: RuntimeConfig with engine settings
        allow_engine_downgrade: Override to allow running with older engine versions
        reset_prefect_db: Delete and recreate Prefect DB after backup
        reset_mlflow_db: Delete and recreate MLflow DB after backup

    Returns:
        PreflightResult with success status and migration details

    Example:
        config = load_runtime_config()
        result = run_preflight(config)
        if not result.success:
            print(f"Pre-flight failed: {result.errors}")
            sys.exit(1)
    """
    errors: list[str] = []
    backup_paths: dict[str, str] = {}
    prefect_migrated = False
    mlflow_migrated = False

    data_dir = config.data_dir

    # Acquire global lock
    lock: LockHandle | None = None
    try:
        lock = acquire_lock(data_dir)
    except Exception as exc:
        errors.append(f"Failed to acquire global lock: {exc}")
        return PreflightResult(success=False, errors=errors)

    try:
        # Import engine migrations (lazy to avoid circular imports)
        from optaic.runtime.engine_migrations import (
            migrate_prefect_db,
            migrate_mlflow_db,
        )

        # Run Prefect migrations if local mode
        if config.prefect.is_local_mode:
            _log_info("Prefect is in local mode, checking migrations...")
            try:
                result = migrate_prefect_db(
                    data_dir,
                    allow_downgrade=allow_engine_downgrade,
                    reset_db=reset_prefect_db,
                )
                if result.success:
                    prefect_migrated = result.action in ("upgrade", "downgrade")
                    if result.backup_path:
                        backup_paths["prefect"] = result.backup_path
                    _log_info(f"Prefect migration: {result.action}")
                else:
                    error_msg = _format_migration_error("Prefect", result)
                    errors.append(error_msg)
                    if result.backup_path:
                        backup_paths["prefect"] = result.backup_path
            except Exception as exc:
                errors.append(f"Prefect migration error: {exc}")

        elif config.prefect.enabled:
            _log_info("Prefect is in remote mode, skipping local migrations")

        # Run MLflow migrations if local mode
        if config.mlflow.is_local_mode:
            _log_info("MLflow is in local mode, checking migrations...")
            try:
                result = migrate_mlflow_db(
                    data_dir,
                    allow_downgrade=allow_engine_downgrade,
                    reset_db=reset_mlflow_db,
                )
                if result.success:
                    mlflow_migrated = result.action in ("upgrade", "downgrade")
                    if result.backup_path:
                        backup_paths["mlflow"] = result.backup_path
                    _log_info(f"MLflow migration: {result.action}")
                else:
                    error_msg = _format_migration_error("MLflow", result)
                    errors.append(error_msg)
                    if result.backup_path:
                        backup_paths["mlflow"] = result.backup_path
            except Exception as exc:
                errors.append(f"MLflow migration error: {exc}")

        elif config.mlflow.enabled:
            _log_info("MLflow is in remote mode, skipping local migrations")

    finally:
        if lock is not None:
            lock.release()

    if errors:
        return PreflightResult(
            success=False,
            prefect_migrated=prefect_migrated,
            mlflow_migrated=mlflow_migrated,
            errors=errors,
            backup_paths=backup_paths if backup_paths else None,
        )

    return PreflightResult(
        success=True,
        prefect_migrated=prefect_migrated,
        mlflow_migrated=mlflow_migrated,
        backup_paths=backup_paths if backup_paths else None,
    )


def _format_migration_error(engine: str, result: object) -> str:
    """Format a migration error with actionable information."""
    error = getattr(result, "error", "Unknown error")
    backup = getattr(result, "backup_path", None)

    msg = f"{engine} migration failed: {error}"
    if backup:
        msg += f"\n  Backup available at: {backup}"
        msg += "\n  To restore, copy the backup back to the original location."
    msg += "\n  Options:"
    msg += (
        "\n    --allow-engine-downgrade  Allow running with older version (dangerous)"
    )
    msg += f"\n    --reset-{engine.lower()}-db  Delete and recreate DB (loses data)"
    return msg


def _log_info(message: str) -> None:
    """Log info message."""
    print(f"[preflight] {_utc_now()} INFO: {message}", flush=True)


def _log_error(message: str) -> None:
    """Log error message."""
    print(f"[preflight] {_utc_now()} ERROR: {message}", flush=True, file=sys.stderr)


# ─────────────────────────────────────────────────────────────
# Integration helper for StartupManager
# ─────────────────────────────────────────────────────────────


def create_preflight_service(
    config: RuntimeConfig,
    *,
    allow_engine_downgrade: bool = False,
    reset_prefect_db: bool = False,
    reset_mlflow_db: bool = False,
) -> tuple[callable, None]:
    """
    Create a preflight service for use with StartupManager.

    Returns:
        Tuple of (start_function, stop_function)

    Usage:
        start_fn, stop_fn = create_preflight_service(config)
        startup_mgr.register_service("engine-migrations", start=start_fn, stop=stop_fn)
    """

    def start() -> bool:
        result = run_preflight(
            config,
            allow_engine_downgrade=allow_engine_downgrade,
            reset_prefect_db=reset_prefect_db,
            reset_mlflow_db=reset_mlflow_db,
        )
        if not result.success:
            for error in result.errors or []:
                _log_error(error)
            return False
        return True

    return start, None
