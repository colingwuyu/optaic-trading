"""Tests for optaic.runtime.ports module."""

from __future__ import annotations

from pathlib import Path
import json
import socket


from optaic.runtime import ports


def test_is_port_available_free_port(tmp_path: Path) -> None:
    """Test that a free port is detected as available."""
    # Find a definitely free port first
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]

    # After closing, it should be available
    assert ports.is_port_available(free_port, "127.0.0.1")


def test_is_port_available_busy_port() -> None:
    """Test that a busy port is detected as unavailable."""
    # Bind a port and keep it bound during the test
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        busy_port = sock.getsockname()[1]

        # While bound, it should not be available
        assert not ports.is_port_available(busy_port, "127.0.0.1")
    finally:
        sock.close()


def test_find_free_port_in_range(tmp_path: Path) -> None:
    """Test finding a free port in a range."""
    # Find a port that is likely free
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        base_port = sock.getsockname()[1]

    # Should find the base port after it's released
    found = ports.find_free_port_in_range(base_port, base_port + 10, "127.0.0.1")
    assert found is not None
    assert base_port <= found <= base_port + 10


def test_find_any_free_port() -> None:
    """Test finding any free port."""
    port = ports.find_any_free_port("127.0.0.1")
    assert port > 0
    # The port should be free (at least momentarily)


def test_port_manager_reserve_preferred(tmp_path: Path) -> None:
    """Test reserving the preferred port when available."""
    manager = ports.PortManager(tmp_path)

    # Use a high port that's likely free
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        preferred = sock.getsockname()[1]

    # After releasing, should get the preferred port
    selected = manager.reserve_port("test", preferred, "127.0.0.1")
    assert selected == preferred

    # Should be persisted
    ports_path = tmp_path / "state" / "ports.json"
    assert ports_path.exists()
    payload = json.loads(ports_path.read_text(encoding="utf-8"))
    assert payload["ports"]["test"] == preferred


def test_port_manager_reuse_previous(tmp_path: Path) -> None:
    """Test that previously allocated ports are reused."""
    # First allocation
    manager1 = ports.PortManager(tmp_path)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        preferred = sock.getsockname()[1]

    selected1 = manager1.reserve_port("test", preferred, "127.0.0.1")

    # Second allocation should reuse the same port
    manager2 = ports.PortManager(tmp_path)
    selected2 = manager2.reserve_port("test", preferred + 100, "127.0.0.1")

    assert selected2 == selected1  # Reused previous allocation


def test_port_manager_collision_resolution(tmp_path: Path) -> None:
    """Test that collisions are resolved by finding next free port."""
    manager = ports.PortManager(tmp_path)

    # Bind a port and keep it bound during the test
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        busy_port = sock.getsockname()[1]

        # While busy, should get a different port
        selected = manager.reserve_port("test", busy_port, "127.0.0.1")
        assert selected != busy_port
        assert selected > 0
    finally:
        sock.close()


def test_port_manager_release_port(tmp_path: Path) -> None:
    """Test releasing a port reservation."""
    manager = ports.PortManager(tmp_path)

    # Reserve a port
    manager.reserve_port("test", 12345, "127.0.0.1")
    assert manager.get_port("test") == 12345

    # Release it
    manager.release_port("test")
    assert manager.get_port("test") is None


def test_port_manager_get_all_ports(tmp_path: Path) -> None:
    """Test getting all reserved ports."""
    manager = ports.PortManager(tmp_path)

    # Find free ports
    free_ports = []
    for _ in range(3):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            free_ports.append(sock.getsockname()[1])

    manager.reserve_port("api", free_ports[0], "127.0.0.1")
    manager.reserve_port("prefect", free_ports[1], "127.0.0.1")
    manager.reserve_port("mlflow", free_ports[2], "127.0.0.1")

    all_ports = manager.get_all_ports()
    assert len(all_ports) == 3
    assert "api" in all_ports
    assert "prefect" in all_ports
    assert "mlflow" in all_ports


def test_reserve_port_convenience(tmp_path: Path) -> None:
    """Test the convenience function."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        preferred = sock.getsockname()[1]

    selected = ports.reserve_port(tmp_path, "test", preferred, "127.0.0.1")
    assert selected == preferred


def test_load_reserved_ports_convenience(tmp_path: Path) -> None:
    """Test the load convenience function."""
    # Reserve some ports first
    manager = ports.PortManager(tmp_path)
    manager.reserve_port("api", 8080, "127.0.0.1")

    loaded = ports.load_reserved_ports(tmp_path)
    assert "api" in loaded


def test_default_ports_defined() -> None:
    """Test that default port assignments are defined."""
    assert ports.DEFAULT_PORTS["api"] == 8080
    assert ports.DEFAULT_PORTS["prefect"] == 4200
    assert ports.DEFAULT_PORTS["mlflow"] == 5000
