"""Tests for optaic.runtime.preflight module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from optaic.runtime import preflight
from optaic.runtime.runtime_config import RuntimeConfig, PrefectConfig, MlflowConfig


def _make_config(
    tmp_path: Path,
    *,
    prefect_enabled: bool = False,
    prefect_local: bool = True,
    mlflow_enabled: bool = False,
    mlflow_local: bool = True,
) -> RuntimeConfig:
    """Create a RuntimeConfig for testing."""
    prefect = PrefectConfig(
        enabled=prefect_enabled,
        api_url="" if prefect_local else "http://remote:4200/api",
    )
    mlflow = MlflowConfig(
        enabled=mlflow_enabled,
        tracking_uri="" if mlflow_local else "http://remote:5000",
    )
    return RuntimeConfig(
        data_dir=tmp_path,
        prefect=prefect,
        mlflow=mlflow,
    )


def test_preflight_result_dataclass() -> None:
    """Test PreflightResult dataclass."""
    result = preflight.PreflightResult(success=True)
    assert result.success
    assert not result.prefect_migrated
    assert not result.mlflow_migrated


def test_run_preflight_no_engines(tmp_path: Path) -> None:
    """Test preflight with no engines enabled."""
    config = _make_config(tmp_path)
    result = preflight.run_preflight(config)
    assert result.success
    assert not result.prefect_migrated
    assert not result.mlflow_migrated


@patch("optaic.runtime.engine_migrations.migrate_prefect_db")
def test_run_preflight_prefect_local_success(mock_migrate: MagicMock, tmp_path: Path) -> None:
    """Test preflight with successful Prefect migration."""
    mock_migrate.return_value = MagicMock(
        success=True,
        action="no_change",
        backup_path=None,
    )

    config = _make_config(tmp_path, prefect_enabled=True, prefect_local=True)
    result = preflight.run_preflight(config)

    assert result.success
    mock_migrate.assert_called_once()


@patch("optaic.runtime.engine_migrations.migrate_prefect_db")
def test_run_preflight_prefect_migration_failure(mock_migrate: MagicMock, tmp_path: Path) -> None:
    """Test preflight fails when Prefect migration fails."""
    mock_migrate.return_value = MagicMock(
        success=False,
        error="Migration failed",
        backup_path=str(tmp_path / "backup"),
    )

    config = _make_config(tmp_path, prefect_enabled=True, prefect_local=True)
    result = preflight.run_preflight(config)

    assert not result.success
    assert result.errors is not None
    assert len(result.errors) == 1
    assert "Prefect" in result.errors[0]
    assert result.backup_paths is not None
    assert "prefect" in result.backup_paths


@patch("optaic.runtime.engine_migrations.migrate_mlflow_db")
def test_run_preflight_mlflow_local_success(mock_migrate: MagicMock, tmp_path: Path) -> None:
    """Test preflight with successful MLflow migration."""
    mock_migrate.return_value = MagicMock(
        success=True,
        action="upgrade",
        backup_path=str(tmp_path / "backup"),
    )

    config = _make_config(tmp_path, mlflow_enabled=True, mlflow_local=True)
    result = preflight.run_preflight(config)

    assert result.success
    assert result.mlflow_migrated
    mock_migrate.assert_called_once()


def test_run_preflight_remote_mode_skips_migration(tmp_path: Path) -> None:
    """Test preflight skips migrations for remote engines."""
    config = _make_config(
        tmp_path,
        prefect_enabled=True,
        prefect_local=False,  # Remote mode
        mlflow_enabled=True,
        mlflow_local=False,  # Remote mode
    )

    # Should not call any migrations
    with patch("optaic.runtime.engine_migrations.migrate_prefect_db") as mock_prefect, \
         patch("optaic.runtime.engine_migrations.migrate_mlflow_db") as mock_mlflow:
        result = preflight.run_preflight(config)

        assert result.success
        mock_prefect.assert_not_called()
        mock_mlflow.assert_not_called()



def test_format_migration_error() -> None:
    """Test error message formatting."""
    result = MagicMock(error="Schema mismatch", backup_path="/path/to/backup")
    msg = preflight._format_migration_error("Prefect", result)

    assert "Prefect" in msg
    assert "Schema mismatch" in msg
    assert "/path/to/backup" in msg
    assert "--allow-engine-downgrade" in msg


def test_create_preflight_service(tmp_path: Path) -> None:
    """Test creating preflight service for StartupManager."""
    config = _make_config(tmp_path)
    start_fn, stop_fn = preflight.create_preflight_service(config)

    assert callable(start_fn)
    assert stop_fn is None
    assert start_fn()  # Should succeed with no engines
