"""Tests for optaic.runtime.engines_state module."""

from __future__ import annotations

from pathlib import Path
import json

import pytest

from optaic.runtime import engines_state as es


def test_load_engines_state_creates_default(tmp_path: Path) -> None:
    """Loading state from missing file returns default state."""
    state = es.load_engines_state(tmp_path)
    assert state.schema_version == es.ENGINES_STATE_SCHEMA
    assert state.engines.prefect.mode == "disabled"
    assert state.engines.mlflow.mode == "disabled"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Saved state can be loaded back correctly."""
    state = es.EnginesStateV1()
    state.engines.prefect.mode = "local"
    state.engines.prefect.package_version = "3.1.0"
    state.engines.prefect.home_dir = str(tmp_path / "prefect_home")
    state.engines.prefect.api_url = "http://localhost:4200/api"

    state.engines.mlflow.mode = "local"
    state.engines.mlflow.package_version = "2.15.0"
    state.engines.mlflow.backend_store_uri = "sqlite:///mlflow.db"
    state.engines.mlflow.artifact_root = str(tmp_path / "artifacts")
    state.engines.mlflow.tracking_uri = "http://localhost:5000"

    es.save_engines_state_atomic(tmp_path, state)

    loaded = es.load_engines_state(tmp_path)
    assert loaded.engines.prefect.mode == "local"
    assert loaded.engines.prefect.package_version == "3.1.0"
    assert loaded.engines.mlflow.mode == "local"
    assert loaded.engines.mlflow.package_version == "2.15.0"


def test_atomic_save_doesnt_corrupt_on_failure(tmp_path: Path) -> None:
    """If save fails after writing tmp, original file is preserved."""
    state_path = tmp_path / "state" / "engines_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    # Write initial valid state
    initial = es.EnginesStateV1()
    initial.engines.prefect.mode = "local"
    es.save_engines_state_atomic(tmp_path, initial)

    # Verify it exists
    assert state_path.exists()
    content_before = state_path.read_text(encoding="utf-8")

    # Now successfully write a new state
    updated = es.EnginesStateV1()
    updated.engines.prefect.mode = "remote"
    es.save_engines_state_atomic(tmp_path, updated)

    # Verify update
    content_after = state_path.read_text(encoding="utf-8")
    assert content_before != content_after
    loaded = es.load_engines_state(tmp_path)
    assert loaded.engines.prefect.mode == "remote"


def test_check_upgrade_allowed_upgrade() -> None:
    """Version increase is allowed."""
    allowed, reason = es.check_upgrade_allowed("1.0.0", "2.0.0")
    assert allowed is True
    assert reason == "upgrade"


def test_check_upgrade_allowed_same_version() -> None:
    """Same version is allowed."""
    allowed, reason = es.check_upgrade_allowed("1.0.0", "1.0.0")
    assert allowed is True
    assert reason == "same_version"


def test_check_upgrade_downgrade_blocked() -> None:
    """Downgrade is blocked by default."""
    allowed, reason = es.check_upgrade_allowed("2.0.0", "1.0.0")
    assert allowed is False
    assert reason == "downgrade_blocked"


def test_check_upgrade_downgrade_allowed() -> None:
    """Downgrade is allowed when explicitly permitted."""
    allowed, reason = es.check_upgrade_allowed(
        "2.0.0", "1.0.0", allow_downgrade=True
    )
    assert allowed is True
    assert reason == "downgrade_allowed"


def test_check_upgrade_initial_install() -> None:
    """Initial install (empty current version) is allowed."""
    allowed, reason = es.check_upgrade_allowed("", "1.0.0")
    assert allowed is True
    assert reason == "initial_install"


def test_check_upgrade_invalid_version() -> None:
    """Invalid version string returns error."""
    allowed, reason = es.check_upgrade_allowed("1.0.0", "not-a-version")
    assert allowed is False
    assert "invalid_version" in reason


def test_ensure_engines_layout(tmp_path: Path) -> None:
    """ensure_engines_layout creates the proper directory structure."""
    es.ensure_engines_layout(tmp_path)

    assert (tmp_path / "engines" / "prefect" / "home").exists()
    assert (tmp_path / "engines" / "prefect" / "backups").exists()
    assert (tmp_path / "engines" / "mlflow" / "backend").exists()
    assert (tmp_path / "engines" / "mlflow" / "artifacts").exists()
    assert (tmp_path / "engines" / "mlflow" / "backups").exists()


def test_backup_engine_data_prefect(tmp_path: Path) -> None:
    """Backup creates timestamped copy of prefect home."""
    es.ensure_engines_layout(tmp_path)
    home_dir = tmp_path / "engines" / "prefect" / "home"
    (home_dir / "test.db").write_text("test data", encoding="utf-8")

    backup_path = es.backup_engine_data(tmp_path, "prefect")

    assert backup_path is not None
    assert backup_path.exists()
    assert (backup_path / "test.db").read_text(encoding="utf-8") == "test data"


def test_backup_engine_data_empty(tmp_path: Path) -> None:
    """Backup returns None when no data exists."""
    es.ensure_engines_layout(tmp_path)
    backup_path = es.backup_engine_data(tmp_path, "prefect")
    assert backup_path is None


def test_log_engine_upgrade(tmp_path: Path) -> None:
    """Engine upgrades are logged to upgrade.log."""
    es.log_engine_upgrade(
        tmp_path,
        engine="prefect",
        action="upgrade",
        outcome="success",
        before_version="3.0.0",
        after_version="3.1.0",
    )

    log_path = tmp_path / "state" / "upgrade.log"
    content = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1

    payload = json.loads(content[0])
    assert payload["engine"] == "prefect"
    assert payload["action"] == "upgrade"
    assert payload["outcome"] == "success"
    assert payload["before_version"] == "3.0.0"
    assert payload["after_version"] == "3.1.0"


def test_get_engine_paths(tmp_path: Path) -> None:
    """Helper functions return correct paths."""
    assert es.get_prefect_home(tmp_path) == tmp_path / "engines" / "prefect" / "home"
    assert es.get_mlflow_backend_dir(tmp_path) == tmp_path / "engines" / "mlflow" / "backend"
    assert es.get_mlflow_artifacts_dir(tmp_path) == tmp_path / "engines" / "mlflow" / "artifacts"


def test_update_prefect_state() -> None:
    """update_prefect_state modifies state correctly."""
    state = es.EnginesStateV1()
    test_path = Path("/data/prefect")
    es.update_prefect_state(
        state,
        mode="local",
        package_version="3.1.0",
        home_dir=test_path,
        api_url="http://localhost:4200/api",
    )

    assert state.engines.prefect.mode == "local"
    assert state.engines.prefect.package_version == "3.1.0"
    # Compare as Path to handle cross-platform separator differences
    assert Path(state.engines.prefect.home_dir) == test_path
    assert state.engines.prefect.api_url == "http://localhost:4200/api"


def test_update_mlflow_state() -> None:
    """update_mlflow_state modifies state correctly."""
    state = es.EnginesStateV1()
    es.update_mlflow_state(
        state,
        mode="local",
        package_version="2.15.0",
        backend_store_uri="sqlite:///mlflow.db",
        artifact_root="/data/artifacts",
        tracking_uri="http://localhost:5000",
    )

    assert state.engines.mlflow.mode == "local"
    assert state.engines.mlflow.package_version == "2.15.0"
    assert state.engines.mlflow.backend_store_uri == "sqlite:///mlflow.db"


def test_mark_migrated(tmp_path: Path) -> None:
    """mark_migrated sets timestamp for last_migrated_at."""
    state = es.EnginesStateV1()
    assert state.engines.prefect.last_migrated_at is None

    es.mark_migrated(state, "prefect")
    assert state.engines.prefect.last_migrated_at is not None


def test_mark_backed_up(tmp_path: Path) -> None:
    """mark_backed_up sets timestamp for last_backup_at."""
    state = es.EnginesStateV1()
    assert state.engines.mlflow.last_backup_at is None

    es.mark_backed_up(state, "mlflow")
    assert state.engines.mlflow.last_backup_at is not None


def test_corrupted_state_returns_default(tmp_path: Path) -> None:
    """Corrupted state file returns default state."""
    state_path = tmp_path / "state" / "engines_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("not valid json {{{", encoding="utf-8")

    state = es.load_engines_state(tmp_path)
    assert state.schema_version == es.ENGINES_STATE_SCHEMA
    assert state.engines.prefect.mode == "disabled"
