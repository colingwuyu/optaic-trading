"""Tests for optaic.runtime.state module."""

from __future__ import annotations

import json
from pathlib import Path


from optaic.runtime import state
from optaic.runtime.runtime_config import RuntimeConfig, PrefectConfig, MlflowConfig


def _make_config(tmp_path: Path) -> RuntimeConfig:
    """Create a RuntimeConfig for testing."""
    return RuntimeConfig(
        data_dir=tmp_path,
        prefect=PrefectConfig(enabled=True),
        mlflow=MlflowConfig(enabled=True),
    )


def test_component_info_dataclass() -> None:
    """Test ComponentInfo dataclass."""
    info = state.ComponentInfo(
        name="prefect",
        version="2.0.0",
        mode="local",
        port=4200,
    )
    assert info.name == "prefect"
    assert info.mode == "local"


def test_installed_state_dataclass() -> None:
    """Test InstalledState dataclass."""
    installed = state.InstalledState(
        optaic_version="1.0.0",
        python_version="3.11.0",
        platform="Windows",
        data_dir="/data",
        updated_at="2024-01-01",
        components={},
        ports={},
    )
    assert installed.optaic_version == "1.0.0"


def test_get_installed_state(tmp_path: Path) -> None:
    """Test building installed state from config."""
    config = _make_config(tmp_path)
    installed = state.get_installed_state(config)

    assert installed.data_dir == str(tmp_path)
    assert "prefect" in installed.components
    assert "mlflow" in installed.components
    assert installed.optaic_version is not None


def test_write_installed_state(tmp_path: Path) -> None:
    """Test writing installed state to disk."""
    config = _make_config(tmp_path)
    path = state.write_installed_state(config)

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "optaic_version" in data
    assert "components" in data


def test_load_installed_state(tmp_path: Path) -> None:
    """Test loading installed state from disk."""
    config = _make_config(tmp_path)
    state.write_installed_state(config)

    loaded = state.load_installed_state(tmp_path)
    assert loaded is not None
    assert loaded.data_dir == str(tmp_path)


def test_load_installed_state_missing(tmp_path: Path) -> None:
    """Test loading non-existent state."""
    loaded = state.load_installed_state(tmp_path)
    assert loaded is None


def test_service_run_state_dataclass() -> None:
    """Test ServiceRunState dataclass."""
    svc = state.ServiceRunState(
        name="prefect-server",
        status="running",
        pid=1234,
    )
    assert svc.name == "prefect-server"
    assert svc.status == "running"


def test_write_services_state(tmp_path: Path) -> None:
    """Test writing services state to disk."""
    services = {
        "prefect-server": state.ServiceRunState(
            name="prefect-server",
            status="running",
            pid=1234,
            port=4200,
            url="http://127.0.0.1:4200/api",
            started_at="2024-01-01T00:00:00Z",
        ),
    }
    path = state.write_services_state(tmp_path, services)

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "services" in data
    assert "prefect-server" in data["services"]


def test_load_services_state(tmp_path: Path) -> None:
    """Test loading services state from disk."""
    services = {
        "mlflow": state.ServiceRunState(
            name="mlflow",
            status="stopped",
        ),
    }
    state.write_services_state(tmp_path, services)

    loaded = state.load_services_state(tmp_path)
    assert loaded is not None
    assert "mlflow" in loaded.services


def test_load_services_state_missing(tmp_path: Path) -> None:
    """Test loading non-existent services state."""
    loaded = state.load_services_state(tmp_path)
    assert loaded is None


def test_update_service_health(tmp_path: Path) -> None:
    """Test updating service health check."""
    services = {
        "api": state.ServiceRunState(name="api", status="running"),
    }
    state.write_services_state(tmp_path, services)

    state.update_service_health(tmp_path, "api", healthy=True)

    loaded = state.load_services_state(tmp_path)
    assert loaded is not None
    assert loaded.services["api"].healthy is True
    assert loaded.services["api"].last_health_check is not None


def test_atomic_write_json(tmp_path: Path) -> None:
    """Test atomic JSON write."""
    path = tmp_path / "test.json"
    state._atomic_write_json(path, {"key": "value"})

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"key": "value"}
    # Temp file should be cleaned up
    assert not path.with_suffix(".tmp").exists()
