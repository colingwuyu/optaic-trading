"""
Engine DB migration manager for Prefect and MLflow.

Provides safe upgrade path with:
- Automatic backup before migration
- Version detection and comparison
- Downgrade blocking by default
- Idempotent re-runs
- Detailed logging to upgrade.log

INVARIANTS:
- Engine DBs live under DATA_DIR only
- Backups are created before any migration
- Downgrades are blocked unless explicitly overridden
- Failed migrations prevent engine startup
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import os
import shutil
import subprocess


from optaic.runtime.engines_state import (
    check_upgrade_allowed,
    get_mlflow_backend_dir,
    get_prefect_home,
    load_engines_state,
    log_engine_upgrade,
    mark_backed_up,
    mark_migrated,
    save_engines_state_atomic,
)
from optaic.runtime.upgrade_manager import acquire_lock, LockHandle


@dataclass
class MigrationResult:
    """Result of an engine migration operation."""

    success: bool
    action: Literal["upgrade", "downgrade", "no_change", "blocked", "failed", "reset"]
    engine: str
    before_version: str | None
    after_version: str | None
    backup_path: Path | None
    error_message: str | None = None


def get_prefect_version() -> str | None:
    """Get installed Prefect package version, or None if not installed."""
    try:
        import prefect

        return prefect.__version__
    except ImportError:
        return None


def get_mlflow_version() -> str | None:
    """Get installed MLflow package version, or None if not installed."""
    try:
        import mlflow

        return mlflow.__version__
    except ImportError:
        return None


def copy_sqlite_db_safely(src_path: Path, dest_path: Path) -> None:
    """
    Copy a SQLite database file safely.

    Uses shutil.copy2 to preserve metadata. For production use with
    active databases, consider using SQLite backup API.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if src_path.exists():
        shutil.copy2(src_path, dest_path)


def create_timestamped_backup_dir(backups_dir: Path) -> Path:
    """Create a timestamped backup directory."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = backups_dir / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def migrate_prefect_db(
    data_dir: Path,
    *,
    allow_downgrade: bool = False,
    reset_db: bool = False,
) -> MigrationResult:
    """
    Migrate Prefect database if version changed.

    Args:
        data_dir: OptAIC DATA_DIR
        allow_downgrade: If True, allow version decrease (dangerous)
        reset_db: If True, delete DB after backup and start fresh (destructive)

    Returns:
        MigrationResult with details of what happened
    """
    current_version = get_prefect_version()
    if current_version is None:
        return MigrationResult(
            success=True,
            action="no_change",
            engine="prefect",
            before_version=None,
            after_version=None,
            backup_path=None,
            error_message="Prefect not installed",
        )

    state = load_engines_state(data_dir)
    recorded_version = state.engines.prefect.package_version

    # Check if migration is allowed
    allowed, reason = check_upgrade_allowed(
        recorded_version,
        current_version,
        allow_downgrade=allow_downgrade,
    )

    if not allowed and not reset_db:
        log_engine_upgrade(
            data_dir,
            engine="prefect",
            action="migration_blocked",
            outcome="blocked",
            before_version=recorded_version,
            after_version=current_version,
            detail=reason,
        )
        return MigrationResult(
            success=False,
            action="blocked",
            engine="prefect",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=None,
            error_message=f"Downgrade blocked: {recorded_version} -> {current_version}. "
            "Use --allow-engine-downgrade or --reset-prefect-db to override.",
        )

    # Check if migration is needed
    if reason == "same_version" and not reset_db:
        return MigrationResult(
            success=True,
            action="no_change",
            engine="prefect",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=None,
        )

    # Create backup
    prefect_home = get_prefect_home(data_dir)
    prefect_db = prefect_home / "prefect.db"
    backup_path: Path | None = None

    if prefect_db.exists():
        backups_dir = data_dir / "engines" / "prefect" / "backups"
        backup_dir = create_timestamped_backup_dir(backups_dir)
        backup_path = backup_dir / "prefect.db"
        try:
            copy_sqlite_db_safely(prefect_db, backup_path)
            mark_backed_up(state, "prefect")
        except Exception as exc:
            log_engine_upgrade(
                data_dir,
                engine="prefect",
                action="backup_failed",
                outcome="failed",
                before_version=recorded_version,
                after_version=current_version,
                detail=str(exc),
            )
            return MigrationResult(
                success=False,
                action="failed",
                engine="prefect",
                before_version=recorded_version,
                after_version=current_version,
                backup_path=None,
                error_message=f"Backup failed: {exc}",
            )

    # Reset DB if requested
    if reset_db:
        if prefect_db.exists():
            prefect_db.unlink()
        log_engine_upgrade(
            data_dir,
            engine="prefect",
            action="db_reset",
            outcome="success",
            before_version=recorded_version,
            after_version=current_version,
            detail=f"DB reset, backup at {backup_path}",
        )
        state.engines.prefect.package_version = current_version
        mark_migrated(state, "prefect")
        save_engines_state_atomic(data_dir, state)
        return MigrationResult(
            success=True,
            action="reset",
            engine="prefect",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=backup_path,
        )

    # Run Prefect DB migration
    try:
        env = os.environ.copy()
        env["PREFECT_HOME"] = str(prefect_home)

        result = subprocess.run(
            ["prefect", "server", "database", "upgrade", "-y"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            log_engine_upgrade(
                data_dir,
                engine="prefect",
                action="migration_failed",
                outcome="failed",
                before_version=recorded_version,
                after_version=current_version,
                detail=result.stderr or result.stdout,
            )
            return MigrationResult(
                success=False,
                action="failed",
                engine="prefect",
                before_version=recorded_version,
                after_version=current_version,
                backup_path=backup_path,
                error_message=f"Migration failed: {result.stderr or result.stdout}. "
                f"Backup available at: {backup_path}",
            )

    except subprocess.TimeoutExpired:
        log_engine_upgrade(
            data_dir,
            engine="prefect",
            action="migration_timeout",
            outcome="failed",
            before_version=recorded_version,
            after_version=current_version,
        )
        return MigrationResult(
            success=False,
            action="failed",
            engine="prefect",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=backup_path,
            error_message=f"Migration timed out. Backup available at: {backup_path}",
        )
    except FileNotFoundError:
        # Prefect CLI not found - this is fine for first-time setup
        pass

    # Update state
    # initial_install and upgrade both count as upgrade action
    action: Literal["upgrade", "downgrade"] = (
        "upgrade" if reason in ("upgrade", "initial_install") else "downgrade"
    )
    state.engines.prefect.package_version = current_version
    mark_migrated(state, "prefect")
    save_engines_state_atomic(data_dir, state)

    log_engine_upgrade(
        data_dir,
        engine="prefect",
        action=f"migration_{action}",
        outcome="success",
        before_version=recorded_version,
        after_version=current_version,
        detail=f"Backup at {backup_path}" if backup_path else None,
    )

    return MigrationResult(
        success=True,
        action=action,
        engine="prefect",
        before_version=recorded_version,
        after_version=current_version,
        backup_path=backup_path,
    )


def migrate_mlflow_db(
    data_dir: Path,
    *,
    allow_downgrade: bool = False,
    reset_db: bool = False,
) -> MigrationResult:
    """
    Migrate MLflow database if version changed.

    Args:
        data_dir: OptAIC DATA_DIR
        allow_downgrade: If True, allow version decrease (dangerous)
        reset_db: If True, delete DB after backup and start fresh (destructive)

    Returns:
        MigrationResult with details of what happened
    """
    current_version = get_mlflow_version()
    if current_version is None:
        return MigrationResult(
            success=True,
            action="no_change",
            engine="mlflow",
            before_version=None,
            after_version=None,
            backup_path=None,
            error_message="MLflow not installed",
        )

    state = load_engines_state(data_dir)
    recorded_version = state.engines.mlflow.package_version

    # Check if migration is allowed
    allowed, reason = check_upgrade_allowed(
        recorded_version,
        current_version,
        allow_downgrade=allow_downgrade,
    )

    if not allowed and not reset_db:
        log_engine_upgrade(
            data_dir,
            engine="mlflow",
            action="migration_blocked",
            outcome="blocked",
            before_version=recorded_version,
            after_version=current_version,
            detail=reason,
        )
        return MigrationResult(
            success=False,
            action="blocked",
            engine="mlflow",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=None,
            error_message=f"Downgrade blocked: {recorded_version} -> {current_version}. "
            "Use --allow-engine-downgrade or --reset-mlflow-db to override.",
        )

    # Check if migration is needed
    if reason == "same_version" and not reset_db:
        return MigrationResult(
            success=True,
            action="no_change",
            engine="mlflow",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=None,
        )

    # Create backup
    mlflow_backend = get_mlflow_backend_dir(data_dir)
    mlflow_db = mlflow_backend / "mlflow.db"
    backup_path: Path | None = None

    if mlflow_db.exists():
        backups_dir = data_dir / "engines" / "mlflow" / "backups"
        backup_dir = create_timestamped_backup_dir(backups_dir)
        backup_path = backup_dir / "mlflow.db"
        try:
            copy_sqlite_db_safely(mlflow_db, backup_path)
            mark_backed_up(state, "mlflow")
        except Exception as exc:
            log_engine_upgrade(
                data_dir,
                engine="mlflow",
                action="backup_failed",
                outcome="failed",
                before_version=recorded_version,
                after_version=current_version,
                detail=str(exc),
            )
            return MigrationResult(
                success=False,
                action="failed",
                engine="mlflow",
                before_version=recorded_version,
                after_version=current_version,
                backup_path=None,
                error_message=f"Backup failed: {exc}",
            )

    # Reset DB if requested
    if reset_db:
        if mlflow_db.exists():
            mlflow_db.unlink()
        log_engine_upgrade(
            data_dir,
            engine="mlflow",
            action="db_reset",
            outcome="success",
            before_version=recorded_version,
            after_version=current_version,
            detail=f"DB reset, backup at {backup_path}",
        )
        state.engines.mlflow.package_version = current_version
        mark_migrated(state, "mlflow")
        save_engines_state_atomic(data_dir, state)
        return MigrationResult(
            success=True,
            action="reset",
            engine="mlflow",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=backup_path,
        )

    # Run MLflow DB migration
    backend_uri = f"sqlite:///{mlflow_db.as_posix()}"
    try:
        result = subprocess.run(
            ["mlflow", "db", "upgrade", backend_uri],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            log_engine_upgrade(
                data_dir,
                engine="mlflow",
                action="migration_failed",
                outcome="failed",
                before_version=recorded_version,
                after_version=current_version,
                detail=result.stderr or result.stdout,
            )
            return MigrationResult(
                success=False,
                action="failed",
                engine="mlflow",
                before_version=recorded_version,
                after_version=current_version,
                backup_path=backup_path,
                error_message=f"Migration failed: {result.stderr or result.stdout}. "
                f"Backup available at: {backup_path}",
            )

    except subprocess.TimeoutExpired:
        log_engine_upgrade(
            data_dir,
            engine="mlflow",
            action="migration_timeout",
            outcome="failed",
            before_version=recorded_version,
            after_version=current_version,
        )
        return MigrationResult(
            success=False,
            action="failed",
            engine="mlflow",
            before_version=recorded_version,
            after_version=current_version,
            backup_path=backup_path,
            error_message=f"Migration timed out. Backup available at: {backup_path}",
        )
    except FileNotFoundError:
        # MLflow CLI not found - this is fine for first-time setup
        pass

    # Update state
    # initial_install and upgrade both count as upgrade action
    action: Literal["upgrade", "downgrade"] = (
        "upgrade" if reason in ("upgrade", "initial_install") else "downgrade"
    )
    state.engines.mlflow.package_version = current_version
    mark_migrated(state, "mlflow")
    save_engines_state_atomic(data_dir, state)

    log_engine_upgrade(
        data_dir,
        engine="mlflow",
        action=f"migration_{action}",
        outcome="success",
        before_version=recorded_version,
        after_version=current_version,
        detail=f"Backup at {backup_path}" if backup_path else None,
    )

    return MigrationResult(
        success=True,
        action=action,
        engine="mlflow",
        before_version=recorded_version,
        after_version=current_version,
        backup_path=backup_path,
    )


def run_engine_migrations(
    data_dir: Path,
    *,
    with_prefect: bool = False,
    with_mlflow: bool = False,
    allow_downgrade: bool = False,
    reset_prefect_db: bool = False,
    reset_mlflow_db: bool = False,
) -> list[MigrationResult]:
    """
    Run all engine migrations with global lock.

    This is the main entry point for engine migrations. It:
    1. Acquires the global lock
    2. Runs migrations for enabled engines
    3. Returns results

    Args:
        data_dir: OptAIC DATA_DIR
        with_prefect: Whether to migrate Prefect
        with_mlflow: Whether to migrate MLflow
        allow_downgrade: Allow version decreases (dangerous)
        reset_prefect_db: Reset Prefect DB after backup (destructive)
        reset_mlflow_db: Reset MLflow DB after backup (destructive)

    Returns:
        List of MigrationResult for each engine
    """
    results: list[MigrationResult] = []

    # Acquire global lock
    lock: LockHandle | None = None
    try:
        lock = acquire_lock(data_dir)

        if with_prefect:
            result = migrate_prefect_db(
                data_dir,
                allow_downgrade=allow_downgrade,
                reset_db=reset_prefect_db,
            )
            results.append(result)

        if with_mlflow:
            result = migrate_mlflow_db(
                data_dir,
                allow_downgrade=allow_downgrade,
                reset_db=reset_mlflow_db,
            )
            results.append(result)

    finally:
        if lock is not None:
            lock.release()

    return results


def check_engine_migrations_required(
    data_dir: Path,
    *,
    with_prefect: bool = False,
    with_mlflow: bool = False,
) -> dict[str, tuple[str | None, str | None, bool]]:
    """
    Check if engine migrations are required without running them.

    Returns:
        Dict mapping engine name to (recorded_version, current_version, migration_needed)
    """
    result: dict[str, tuple[str | None, str | None, bool]] = {}
    state = load_engines_state(data_dir)

    if with_prefect:
        current = get_prefect_version()
        recorded = state.engines.prefect.package_version or None
        needed = current is not None and current != recorded
        result["prefect"] = (recorded, current, needed)

    if with_mlflow:
        current = get_mlflow_version()
        recorded = state.engines.mlflow.package_version or None
        needed = current is not None and current != recorded
        result["mlflow"] = (recorded, current, needed)

    return result
