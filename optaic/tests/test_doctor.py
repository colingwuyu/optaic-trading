"""Tests for optaic.runtime.doctor module."""

from __future__ import annotations

import json
from pathlib import Path


from optaic.runtime import doctor
from optaic.runtime.runtime_config import RuntimeConfig, PrefectConfig, MlflowConfig


def _make_config(
    tmp_path: Path,
    *,
    prefect_enabled: bool = False,
    mlflow_enabled: bool = False,
) -> RuntimeConfig:
    """Create a RuntimeConfig for testing."""
    prefect = PrefectConfig(enabled=prefect_enabled)
    mlflow = MlflowConfig(enabled=mlflow_enabled)
    return RuntimeConfig(
        data_dir=tmp_path,
        prefect=prefect,
        mlflow=mlflow,
    )


def test_diagnostic_item_dataclass() -> None:
    """Test DiagnosticItem dataclass."""
    item = doctor.DiagnosticItem(
        name="Test",
        status="ok",
        message="All good",
    )
    assert item.name == "Test"
    assert item.status == "ok"


def test_doctor_report_has_errors() -> None:
    """Test DoctorReport.has_errors()."""
    report = doctor.DoctorReport(data_dir="/test", checked_at="now")
    assert not report.has_errors()

    report.items.append(doctor.DiagnosticItem(name="test", status="error", message="fail"))
    assert report.has_errors()


def test_doctor_report_has_warnings() -> None:
    """Test DoctorReport.has_warnings()."""
    report = doctor.DoctorReport(data_dir="/test", checked_at="now")
    assert not report.has_warnings()

    report.items.append(doctor.DiagnosticItem(name="test", status="warn", message="warning"))
    assert report.has_warnings()


def test_run_doctor_basic(tmp_path: Path) -> None:
    """Test run_doctor with minimal configuration."""
    config = _make_config(tmp_path)
    report = doctor.run_doctor(config)

    assert report.data_dir == str(tmp_path)
    assert len(report.items) > 0
    # Should have DATA_DIR check
    assert any(item.name == "DATA_DIR" for item in report.items)


def test_run_doctor_data_dir_exists(tmp_path: Path) -> None:
    """Test DATA_DIR check passes when dir exists."""
    config = _make_config(tmp_path)
    report = doctor.run_doctor(config)

    data_dir_item = next(i for i in report.items if i.name == "DATA_DIR")
    assert data_dir_item.status == "ok"


def test_run_doctor_data_dir_missing(tmp_path: Path) -> None:
    """Test DATA_DIR check fails when dir missing."""
    missing_dir = tmp_path / "nonexistent"
    config = _make_config(missing_dir)
    report = doctor.run_doctor(config)

    data_dir_item = next(i for i in report.items if i.name == "DATA_DIR")
    assert data_dir_item.status == "error"


def test_run_doctor_engines_disabled(tmp_path: Path) -> None:
    """Test engine diagnostics when disabled."""
    config = _make_config(tmp_path)
    report = doctor.run_doctor(config)

    assert "prefect" in report.engines
    assert report.engines["prefect"]["enabled"] is False


def test_run_doctor_prefect_enabled(tmp_path: Path) -> None:
    """Test engine diagnostics when Prefect enabled."""
    config = _make_config(tmp_path, prefect_enabled=True)
    report = doctor.run_doctor(config)

    assert report.engines["prefect"]["enabled"] is True
    assert report.engines["prefect"]["mode"] == "local"


def test_run_doctor_stale_pids_auto_clean(tmp_path: Path) -> None:
    """Test stale pid cleanup."""
    # Create a stale pidfile
    pids_dir = tmp_path / "state" / "pids"
    pids_dir.mkdir(parents=True)
    (pids_dir / "stale.pid").write_text("99999\n", encoding="utf-8")

    config = _make_config(tmp_path)
    report = doctor.run_doctor(config, auto_clean_stale_pids=True)

    # Should have cleaned the stale pid
    stale_item = next((i for i in report.items if i.name == "Stale PIDs"), None)
    assert stale_item is not None


def test_format_doctor_report(tmp_path: Path) -> None:
    """Test report formatting."""
    config = _make_config(tmp_path)
    report = doctor.run_doctor(config)
    output = doctor.format_doctor_report(report, color=False)

    assert "OptAIC Doctor Report" in output
    assert str(tmp_path) in output
    assert "DATA_DIR" in output


def test_check_last_migration_no_state(tmp_path: Path) -> None:
    """Test migration check with no state file."""
    items = doctor._check_last_migration(tmp_path)
    assert len(items) == 1
    assert items[0].status == "info"


def test_check_last_migration_with_state(tmp_path: Path) -> None:
    """Test migration check with state file."""
    state_dir = tmp_path / "engines"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "engines_state.json"
    state_file.write_text(json.dumps({
        "prefect": {
            "package_version": "2.0.0",
            "last_migration_at": "2024-01-01T00:00:00Z",
        }
    }), encoding="utf-8")

    items = doctor._check_last_migration(tmp_path)
    assert any("Prefect" in item.name for item in items)


def test_get_log_tail(tmp_path: Path) -> None:
    """Test log tail extraction."""
    log_file = tmp_path / "test.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

    result = doctor._get_log_tail(log_file, lines=2)
    assert "line2" in result
    assert "line3" in result


def test_get_log_tail_missing_file(tmp_path: Path) -> None:
    """Test log tail with missing file."""
    log_file = tmp_path / "missing.log"
    result = doctor._get_log_tail(log_file)
    assert result is None
