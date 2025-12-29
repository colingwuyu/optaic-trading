"""
Engine state tracking for Prefect and MLflow orchestration engines.

This module provides:
- Pydantic models for engine state persistence
- Atomic state load/save operations
- Upgrade/downgrade invariant checks
- Backup functionality for engine data

INVARIANTS:
- OptAIC never stores mutable operational state inside the wheel.
- Engine DBs live under DATA_DIR only.
- If package version increases → run engine DB migrations (with backup first).
- If package version decreases (downgrade) → block by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import json
import shutil

from packaging.version import Version, InvalidVersion
from pydantic import BaseModel, Field

ENGINES_STATE_SCHEMA = 1


class PrefectEngineState(BaseModel):
    """State for the Prefect orchestration engine."""

    mode: Literal["disabled", "local", "remote"] = "disabled"
    package_version: str = ""
    home_dir: str = ""
    api_url: str = ""
    last_migrated_at: str | None = None
    last_backup_at: str | None = None


class MlflowEngineState(BaseModel):
    """State for the MLflow tracking/registry engine."""

    mode: Literal["disabled", "local", "remote"] = "disabled"
    package_version: str = ""
    backend_store_uri: str = ""
    artifact_root: str = ""
    tracking_uri: str = ""
    last_migrated_at: str | None = None
    last_backup_at: str | None = None


class EnginesState(BaseModel):
    """Container for engine state with prefect and mlflow entries."""

    prefect: PrefectEngineState = Field(default_factory=PrefectEngineState)
    mlflow: MlflowEngineState = Field(default_factory=MlflowEngineState)


class EnginesStateV1(BaseModel):
    """
    Root state model for engine tracking.

    Schema version is used for future migrations of the state file itself.
    """

    schema_version: int = ENGINES_STATE_SCHEMA
    engines: EnginesState = Field(default_factory=EnginesState)


def ensure_engines_layout(data_dir: Path) -> None:
    """
    Create the engine-specific directory structure under DATA_DIR.

    Structure:
        DATA_DIR/
          engines/
            prefect/
              home/         # PREFECT_HOME
              backups/      # Pre-migration backups
            mlflow/
              backend/      # mlflow.db location
              artifacts/    # Default artifact root
              backups/      # Pre-migration backups
    """
    engines_dir = data_dir / "engines"

    # Prefect directories
    (engines_dir / "prefect" / "home").mkdir(parents=True, exist_ok=True)
    (engines_dir / "prefect" / "backups").mkdir(parents=True, exist_ok=True)

    # MLflow directories
    (engines_dir / "mlflow" / "backend").mkdir(parents=True, exist_ok=True)
    (engines_dir / "mlflow" / "artifacts").mkdir(parents=True, exist_ok=True)
    (engines_dir / "mlflow" / "backups").mkdir(parents=True, exist_ok=True)


def load_engines_state(data_dir: Path) -> EnginesStateV1:
    """
    Load engine state from DATA_DIR/state/engines_state.json.

    If the file does not exist, returns a default state with disabled engines.
    """
    state_path = data_dir / "state" / "engines_state.json"
    if not state_path.exists():
        return EnginesStateV1()

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return EnginesStateV1.model_validate(payload)
    except Exception:
        # If the file is corrupted, return default state
        return EnginesStateV1()


def save_engines_state_atomic(data_dir: Path, state: EnginesStateV1) -> None:
    """
    Save engine state atomically to DATA_DIR/state/engines_state.json.

    Uses write-to-temp + rename pattern to ensure atomic writes.
    """
    state_path = data_dir / "state" / "engines_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    payload = state.model_dump(mode="json")
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(state_path)


def check_upgrade_allowed(
    current_version: str,
    new_version: str,
    *,
    allow_downgrade: bool = False,
) -> tuple[bool, str]:
    """
    Check whether a version transition is allowed.

    Returns:
        (allowed, reason) tuple

    Upgrade invariants:
        - Version increase: allowed (migrations should run with backup)
        - Version equal: allowed (no-op)
        - Version decrease: blocked by default unless allow_downgrade=True
    """
    if not current_version or not new_version:
        return True, "initial_install"

    try:
        current = Version(current_version)
        new = Version(new_version)
    except InvalidVersion as exc:
        return False, f"invalid_version: {exc}"

    if new > current:
        return True, "upgrade"
    if new == current:
        return True, "same_version"

    # Downgrade case
    if allow_downgrade:
        return True, "downgrade_allowed"
    return False, "downgrade_blocked"


def backup_engine_data(
    data_dir: Path,
    engine_name: Literal["prefect", "mlflow"],
) -> Path | None:
    """
    Create a timestamped backup of engine data before migration.

    Returns the backup path, or None if no data exists to backup.
    """
    engines_dir = data_dir / "engines" / engine_name
    backups_dir = engines_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Determine source directory based on engine
    if engine_name == "prefect":
        source_dir = engines_dir / "home"
    else:  # mlflow
        source_dir = engines_dir / "backend"

    if not source_dir.exists() or not any(source_dir.iterdir()):
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"{engine_name}_{timestamp}"
    backup_path = backups_dir / backup_name

    shutil.copytree(source_dir, backup_path)
    return backup_path


def log_engine_upgrade(
    data_dir: Path,
    *,
    engine: str,
    action: str,
    outcome: str,
    before_version: str | None = None,
    after_version: str | None = None,
    detail: str | None = None,
) -> None:
    """
    Append an engine upgrade event to the upgrade log.

    Uses the same upgrade.log as tool upgrades for unified audit trail.
    """
    log_path = data_dir / "state" / "upgrade.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": engine,
        "action": action,
        "outcome": outcome,
        "before_version": before_version,
        "after_version": after_version,
        "detail": detail,
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def get_prefect_home(data_dir: Path) -> Path:
    """Return the PREFECT_HOME path under DATA_DIR."""
    return data_dir / "engines" / "prefect" / "home"


def get_mlflow_backend_dir(data_dir: Path) -> Path:
    """Return the MLflow backend store directory under DATA_DIR."""
    return data_dir / "engines" / "mlflow" / "backend"


def get_mlflow_artifacts_dir(data_dir: Path) -> Path:
    """Return the MLflow artifacts root directory under DATA_DIR."""
    return data_dir / "engines" / "mlflow" / "artifacts"


def update_prefect_state(
    state: EnginesStateV1,
    *,
    mode: Literal["disabled", "local", "remote"],
    package_version: str,
    home_dir: Path,
    api_url: str,
) -> EnginesStateV1:
    """Update prefect engine state with new values."""
    state.engines.prefect.mode = mode
    state.engines.prefect.package_version = package_version
    state.engines.prefect.home_dir = str(home_dir)
    state.engines.prefect.api_url = api_url
    return state


def update_mlflow_state(
    state: EnginesStateV1,
    *,
    mode: Literal["disabled", "local", "remote"],
    package_version: str,
    backend_store_uri: str,
    artifact_root: str,
    tracking_uri: str,
) -> EnginesStateV1:
    """Update mlflow engine state with new values."""
    state.engines.mlflow.mode = mode
    state.engines.mlflow.package_version = package_version
    state.engines.mlflow.backend_store_uri = backend_store_uri
    state.engines.mlflow.artifact_root = artifact_root
    state.engines.mlflow.tracking_uri = tracking_uri
    return state


def mark_migrated(
    state: EnginesStateV1,
    engine: Literal["prefect", "mlflow"],
) -> EnginesStateV1:
    """Mark engine as having completed migration."""
    now = datetime.now(timezone.utc).isoformat()
    if engine == "prefect":
        state.engines.prefect.last_migrated_at = now
    else:
        state.engines.mlflow.last_migrated_at = now
    return state


def mark_backed_up(
    state: EnginesStateV1,
    engine: Literal["prefect", "mlflow"],
) -> EnginesStateV1:
    """Mark engine as having completed backup."""
    now = datetime.now(timezone.utc).isoformat()
    if engine == "prefect":
        state.engines.prefect.last_backup_at = now
    else:
        state.engines.mlflow.last_backup_at = now
    return state
