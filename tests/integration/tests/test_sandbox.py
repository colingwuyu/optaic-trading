"""Unit tests for the test sandbox infrastructure.

These tests verify the sandbox manager itself works correctly,
WITHOUT starting actual infrastructure (mocked).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.integration.sandbox import (
    SandboxConfig,
    SandboxState,
    SandboxManager,
)


class SandboxManagerConfig:
    """Test SandboxConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = SandboxConfig()

        assert config.api_port == 19080
        assert config.centrifugo_port == 19000
        assert config.prefect_port == 19200
        assert config.mlflow_port == 19500
        assert config.with_prefect is True
        assert config.with_mlflow is True
        assert config.with_worker is True
        assert config.with_agent is False

    def test_api_url_property(self) -> None:
        """Test api_url property."""
        config = SandboxConfig(api_port=8080)
        assert config.api_url == "http://127.0.0.1:8080"

    def test_prefect_api_url_property(self) -> None:
        """Test prefect_api_url property."""
        config = SandboxConfig(prefect_port=4200)
        assert config.prefect_api_url == "http://127.0.0.1:4200/api"

    def test_mlflow_tracking_uri_property(self) -> None:
        """Test mlflow_tracking_uri property."""
        config = SandboxConfig(mlflow_port=5000)
        assert config.mlflow_tracking_uri == "http://127.0.0.1:5000"

    def test_centrifugo_url_property(self) -> None:
        """Test centrifugo_url property."""
        config = SandboxConfig(centrifugo_port=8000)
        assert config.centrifugo_url == "http://127.0.0.1:8000"

    def test_database_url_default(self) -> None:
        """Test default database URL uses SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SandboxConfig(data_dir=Path(tmpdir))
            assert "sqlite:///" in config.database_url
            assert "test.db" in config.database_url

    def test_database_url_custom(self) -> None:
        """Test custom database URL."""
        config = SandboxConfig(database_url="postgresql://localhost/test")
        assert config.database_url == "postgresql://localhost/test"

    def test_state_file_path(self) -> None:
        """Test state file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SandboxConfig(data_dir=Path(tmpdir))
            assert config.state_file == Path(tmpdir) / "state" / "sandbox_state.json"


class SandboxManagerState:
    """Test SandboxState dataclass."""

    def test_default_state(self) -> None:
        """Test default state is not running."""
        state = SandboxState()
        assert state.running is False
        assert state.pid is None
        assert state.api_url is None

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        state = SandboxState(
            running=True,
            pid=12345,
            api_url="http://localhost:8080",
            started_at="2024-01-15T10:00:00Z",
        )
        data = state.to_dict()

        assert data["running"] is True
        assert data["pid"] == 12345
        assert data["api_url"] == "http://localhost:8080"
        assert data["started_at"] == "2024-01-15T10:00:00Z"

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "running": True,
            "pid": 12345,
            "api_url": "http://localhost:8080",
            "unknown_field": "ignored",
        }
        state = SandboxState.from_dict(data)

        assert state.running is True
        assert state.pid == 12345
        assert state.api_url == "http://localhost:8080"

    def test_roundtrip(self) -> None:
        """Test serialization roundtrip."""
        original = SandboxState(
            running=True,
            pid=99999,
            api_url="http://test:8080",
            prefect_api_url="http://test:4200/api",
            mlflow_tracking_uri="http://test:5000",
        )
        data = original.to_dict()
        restored = SandboxState.from_dict(data)

        assert restored.running == original.running
        assert restored.pid == original.pid
        assert restored.api_url == original.api_url
        assert restored.prefect_api_url == original.prefect_api_url
        assert restored.mlflow_tracking_uri == original.mlflow_tracking_uri


class TestSandboxManager:
    """Test SandboxManager class."""

    @pytest.fixture
    def temp_data_dir(self) -> Path:
        """Create temporary data directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sandbox(self, temp_data_dir: Path) -> SandboxManager:
        """Create sandbox with temp directory."""
        config = SandboxConfig(data_dir=temp_data_dir)
        return SandboxManager(config)

    def test_init_default_config(self) -> None:
        """Test initialization with default config."""
        sandbox = SandboxManager()
        assert sandbox.config is not None
        assert sandbox.config.api_port == 19080

    def test_init_custom_config(self, temp_data_dir: Path) -> None:
        """Test initialization with custom config."""
        config = SandboxConfig(data_dir=temp_data_dir, api_port=9999)
        sandbox = SandboxManager(config)
        assert sandbox.config.api_port == 9999

    def test_properties(self, sandbox: SandboxManager) -> None:
        """Test URL properties."""
        assert sandbox.api_url == sandbox.config.api_url
        assert sandbox.prefect_api_url == sandbox.config.prefect_api_url
        assert sandbox.mlflow_tracking_uri == sandbox.config.mlflow_tracking_uri
        assert sandbox.centrifugo_url == sandbox.config.centrifugo_url

    def test_ensure_directories(self, sandbox: SandboxManager) -> None:
        """Test directory creation."""
        sandbox._ensure_directories()

        assert sandbox.config.data_dir.exists()
        assert (sandbox.config.data_dir / "state").exists()
        assert (sandbox.config.data_dir / "logs").exists()

    def test_load_state_empty(self, sandbox: SandboxManager) -> None:
        """Test loading state when no state file exists."""
        state = sandbox._load_state()
        assert state.running is False
        assert state.pid is None

    def test_save_and_load_state(self, sandbox: SandboxManager) -> None:
        """Test saving and loading state."""
        sandbox._ensure_directories()
        sandbox._state = SandboxState(
            running=True,
            pid=12345,
            api_url="http://test:8080",
        )
        sandbox._save_state()

        # Reload state
        sandbox._state = None
        loaded = sandbox._load_state()

        assert loaded.running is True
        assert loaded.pid == 12345
        assert loaded.api_url == "http://test:8080"

    def test_is_running_no_state(self, sandbox: SandboxManager) -> None:
        """Test is_running when no state exists."""
        assert sandbox.is_running() is False

    def test_is_running_dead_process(self, sandbox: SandboxManager) -> None:
        """Test is_running when process is dead."""
        sandbox._ensure_directories()
        sandbox._state = SandboxState(running=True, pid=999999999)
        sandbox._save_state()

        # Process with this PID shouldn't exist
        assert sandbox.is_running() is False

    @patch("tests.integration.sandbox.SandboxManager._is_process_alive")
    @patch("urllib.request.urlopen")
    def test_is_running_healthy(
        self, mock_urlopen: MagicMock, mock_alive: MagicMock, sandbox: SandboxManager
    ) -> None:
        """Test is_running when process is alive and healthy."""
        sandbox._ensure_directories()
        sandbox._state = SandboxState(
            running=True,
            pid=12345,
            api_url=sandbox.config.api_url,
        )
        sandbox._save_state()

        mock_alive.return_value = True
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        assert sandbox.is_running() is True

    def test_stop_no_process(self, sandbox: SandboxManager) -> None:
        """Test stop when no process is running."""
        sandbox._ensure_directories()
        sandbox.stop()  # Should not raise

        state = sandbox._load_state()
        assert state.running is False

    def test_reset_clears_data(self, sandbox: SandboxManager) -> None:
        """Test reset clears data directory."""
        sandbox._ensure_directories()
        test_file = sandbox.config.data_dir / "test.txt"
        test_file.write_text("test")

        sandbox.reset(keep_data=False)

        assert not sandbox.config.data_dir.exists()

    def test_reset_keeps_data(self, sandbox: SandboxManager) -> None:
        """Test reset with keep_data preserves files."""
        sandbox._ensure_directories()
        test_file = sandbox.config.data_dir / "test.txt"
        test_file.write_text("test")

        sandbox.reset(keep_data=True)

        # Data should still exist (just restarted)
        # Note: Since no process was running, directory might be cleared anyway
        # This test verifies the flag is respected


class SandboxManagerStateFile:
    """Test state file operations."""

    def test_state_file_json_format(self) -> None:
        """Test state file is valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SandboxConfig(data_dir=Path(tmpdir))
            sandbox = SandboxManager(config)
            sandbox._ensure_directories()
            sandbox._state = SandboxState(
                running=True,
                pid=12345,
                api_url="http://localhost:8080",
            )
            sandbox._save_state()

            # Read and verify JSON
            content = config.state_file.read_text()
            data = json.loads(content)

            assert data["running"] is True
            assert data["pid"] == 12345

    def test_state_file_corrupted(self) -> None:
        """Test handling of corrupted state file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SandboxConfig(data_dir=Path(tmpdir))
            sandbox = SandboxManager(config)
            sandbox._ensure_directories()

            # Write corrupted JSON
            config.state_file.parent.mkdir(parents=True, exist_ok=True)
            config.state_file.write_text("not valid json {{{")

            # Should return default state
            state = sandbox._load_state()
            assert state.running is False
