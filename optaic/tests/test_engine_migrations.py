"""Tests for optaic.runtime.engine_migrations module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock
import json

import pytest

from optaic.runtime import engine_migrations as em
from optaic.runtime import engines_state as es


def test_get_prefect_version() -> None:
    """Test getting Prefect version."""
    # Actually installed in dev environment
    version = em.get_prefect_version()
    # Should return a version string or None
    assert version is None or isinstance(version, str)


def test_get_mlflow_version() -> None:
    """Test getting MLflow version."""
    # Actually installed in dev environment
    version = em.get_mlflow_version()
    # Should return a version string or None
    assert version is None or isinstance(version, str)


def test_copy_sqlite_db_safely(tmp_path: Path) -> None:
    """Test safe SQLite DB copy."""
    src = tmp_path / "source" / "test.db"
    src.parent.mkdir(parents=True)
    src.write_text("test database content", encoding="utf-8")

    dest = tmp_path / "dest" / "backup" / "test.db"
    em.copy_sqlite_db_safely(src, dest)

    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "test database content"


def test_copy_sqlite_db_safely_missing_source(tmp_path: Path) -> None:
    """Test copy with missing source doesn't error."""
    src = tmp_path / "missing.db"
    dest = tmp_path / "dest.db"

    # Should not raise, just do nothing
    em.copy_sqlite_db_safely(src, dest)
    assert not dest.exists()


def test_create_timestamped_backup_dir(tmp_path: Path) -> None:
    """Test timestamped backup directory creation."""
    backups_dir = tmp_path / "backups"
    backup_dir = em.create_timestamped_backup_dir(backups_dir)

    assert backup_dir.exists()
    assert backup_dir.parent == backups_dir
    # Name should be timestamp format YYYYMMDD_HHMMSS
    assert len(backup_dir.name) == 15  # 8 + 1 + 6


def test_migrate_prefect_db_not_installed(tmp_path: Path) -> None:
    """Test migration when Prefect is not installed."""
    with patch.object(em, "get_prefect_version", return_value=None):
        result = em.migrate_prefect_db(tmp_path)

    assert result.success is True
    assert result.action == "no_change"
    assert result.engine == "prefect"
    assert "not installed" in (result.error_message or "")


def test_migrate_mlflow_db_not_installed(tmp_path: Path) -> None:
    """Test migration when MLflow is not installed."""
    with patch.object(em, "get_mlflow_version", return_value=None):
        result = em.migrate_mlflow_db(tmp_path)

    assert result.success is True
    assert result.action == "no_change"
    assert result.engine == "mlflow"
    assert "not installed" in (result.error_message or "")


def test_migrate_prefect_db_initial_install(tmp_path: Path) -> None:
    """Test Prefect migration on initial install (no recorded version)."""
    es.ensure_engines_layout(tmp_path)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = em.migrate_prefect_db(tmp_path)

    assert result.success is True
    assert result.action == "upgrade"
    assert result.after_version == "3.1.0"

    # Check state was updated
    state = es.load_engines_state(tmp_path)
    assert state.engines.prefect.package_version == "3.1.0"


def test_migrate_prefect_db_same_version(tmp_path: Path) -> None:
    """Test Prefect migration with same version is no-op."""
    es.ensure_engines_layout(tmp_path)

    # Set up state with matching version
    state = es.EnginesStateV1()
    state.engines.prefect.package_version = "3.1.0"
    es.save_engines_state_atomic(tmp_path, state)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        result = em.migrate_prefect_db(tmp_path)

    assert result.success is True
    assert result.action == "no_change"


def test_migrate_prefect_db_upgrade_with_backup(tmp_path: Path) -> None:
    """Test Prefect migration creates backup on upgrade."""
    es.ensure_engines_layout(tmp_path)

    # Set up state with older version
    state = es.EnginesStateV1()
    state.engines.prefect.package_version = "3.0.0"
    es.save_engines_state_atomic(tmp_path, state)

    # Create existing DB
    prefect_home = es.get_prefect_home(tmp_path)
    prefect_db = prefect_home / "prefect.db"
    prefect_db.write_text("old db content", encoding="utf-8")

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = em.migrate_prefect_db(tmp_path)

    assert result.success is True
    assert result.action == "upgrade"
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.read_text(encoding="utf-8") == "old db content"


def test_migrate_prefect_db_downgrade_blocked(tmp_path: Path) -> None:
    """Test Prefect downgrade is blocked by default."""
    es.ensure_engines_layout(tmp_path)

    # Set up state with newer version
    state = es.EnginesStateV1()
    state.engines.prefect.package_version = "3.2.0"
    es.save_engines_state_atomic(tmp_path, state)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        result = em.migrate_prefect_db(tmp_path)

    assert result.success is False
    assert result.action == "blocked"
    assert "Downgrade blocked" in (result.error_message or "")


def test_migrate_prefect_db_downgrade_allowed(tmp_path: Path) -> None:
    """Test Prefect downgrade is allowed with flag."""
    es.ensure_engines_layout(tmp_path)

    # Set up state with newer version
    state = es.EnginesStateV1()
    state.engines.prefect.package_version = "3.2.0"
    es.save_engines_state_atomic(tmp_path, state)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = em.migrate_prefect_db(tmp_path, allow_downgrade=True)

    assert result.success is True
    assert result.action == "downgrade"


def test_migrate_prefect_db_reset(tmp_path: Path) -> None:
    """Test Prefect DB reset creates backup and deletes DB."""
    es.ensure_engines_layout(tmp_path)

    # Set up state
    state = es.EnginesStateV1()
    state.engines.prefect.package_version = "3.0.0"
    es.save_engines_state_atomic(tmp_path, state)

    # Create existing DB
    prefect_home = es.get_prefect_home(tmp_path)
    prefect_db = prefect_home / "prefect.db"
    prefect_db.write_text("old db content", encoding="utf-8")

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        result = em.migrate_prefect_db(tmp_path, reset_db=True)

    assert result.success is True
    assert result.action == "reset"
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert not prefect_db.exists()  # DB was deleted


def test_migrate_mlflow_db_upgrade_with_backup(tmp_path: Path) -> None:
    """Test MLflow migration creates backup on upgrade."""
    es.ensure_engines_layout(tmp_path)

    # Set up state with older version
    state = es.EnginesStateV1()
    state.engines.mlflow.package_version = "2.14.0"
    es.save_engines_state_atomic(tmp_path, state)

    # Create existing DB
    mlflow_backend = es.get_mlflow_backend_dir(tmp_path)
    mlflow_db = mlflow_backend / "mlflow.db"
    mlflow_db.write_text("old db content", encoding="utf-8")

    with patch.object(em, "get_mlflow_version", return_value="2.15.0"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = em.migrate_mlflow_db(tmp_path)

    assert result.success is True
    assert result.action == "upgrade"
    assert result.backup_path is not None
    assert result.backup_path.exists()


def test_check_engine_migrations_required(tmp_path: Path) -> None:
    """Test checking if migrations are required."""
    es.ensure_engines_layout(tmp_path)

    # Set up state
    state = es.EnginesStateV1()
    state.engines.prefect.package_version = "3.0.0"
    state.engines.mlflow.package_version = "2.14.0"
    es.save_engines_state_atomic(tmp_path, state)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        with patch.object(em, "get_mlflow_version", return_value="2.14.0"):
            result = em.check_engine_migrations_required(
                tmp_path, with_prefect=True, with_mlflow=True
            )

    assert result["prefect"] == ("3.0.0", "3.1.0", True)  # Migration needed
    assert result["mlflow"] == ("2.14.0", "2.14.0", False)  # No migration needed


def test_run_engine_migrations(tmp_path: Path) -> None:
    """Test running all engine migrations."""
    es.ensure_engines_layout(tmp_path)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        with patch.object(em, "get_mlflow_version", return_value="2.15.0"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                results = em.run_engine_migrations(
                    tmp_path, with_prefect=True, with_mlflow=True
                )

    assert len(results) == 2
    assert all(r.success for r in results)


def test_migration_logs_to_upgrade_log(tmp_path: Path) -> None:
    """Test that migrations are logged to upgrade.log."""
    es.ensure_engines_layout(tmp_path)

    with patch.object(em, "get_prefect_version", return_value="3.1.0"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            em.migrate_prefect_db(tmp_path)

    log_path = tmp_path / "state" / "upgrade.log"
    assert log_path.exists()

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1

    last_entry = json.loads(lines[-1])
    assert last_entry["engine"] == "prefect"
    assert "migration" in last_entry["action"]
