"""
Port reservation with deterministic allocation and collision handling.

Provides stable port allocation across restarts:
- Preferred ports are tried first
- If busy, next free port in bounded range is selected
- Selections persisted to DATA_DIR/state/ports.json
- Previous allocations reused when available

PORTS MANAGED:
- api_port (8080)
- centrifugo_port (8081)
- redis_port (6379, optional)
- prefect_port (4200, optional)
- mlflow_port (5000, optional)
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# Port availability checking
# ─────────────────────────────────────────────────────────────


def is_port_available(port: int, bind_host: str = "127.0.0.1") -> bool:
    """
    Check if a port is available for binding.

    Args:
        port: Port number to check
        bind_host: Host to bind to

    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Don't use SO_REUSEADDR so we can detect truly busy ports
            sock.bind((bind_host, port))
            return True
    except OSError:
        return False


def find_free_port_in_range(
    start: int,
    end: int,
    bind_host: str = "127.0.0.1",
) -> int | None:
    """
    Find a free port in the given range.

    Args:
        start: Starting port (inclusive)
        end: Ending port (inclusive)
        bind_host: Host to bind to

    Returns:
        First available port, or None if all ports in range are busy
    """
    for port in range(start, end + 1):
        if is_port_available(port, bind_host):
            return port
    return None


def find_any_free_port(bind_host: str = "127.0.0.1") -> int:
    """
    Find any free port by letting the OS assign one.

    Args:
        bind_host: Host to bind to

    Returns:
        A free port number
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind_host, 0))
        return sock.getsockname()[1]


# ─────────────────────────────────────────────────────────────
# Port reservation with persistence
# ─────────────────────────────────────────────────────────────


class PortManager:
    """
    Manages port allocation with deterministic behavior.

    Ports are persisted to DATA_DIR/state/ports.json to ensure
    stable allocations across restarts.
    """

    # Default port range for collision resolution
    PORT_RANGE_SIZE = 50

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._ports: dict[str, int] = {}
        self._ports_path = data_dir / "state" / "ports.json"
        self._load_ports()

    def _load_ports(self) -> None:
        """Load previously allocated ports from disk."""
        if not self._ports_path.exists():
            return
        try:
            payload = json.loads(self._ports_path.read_text(encoding="utf-8"))
            self._ports = payload.get("ports", {})
        except Exception:
            self._ports = {}

    def _save_ports(self) -> None:
        """Atomically save port allocations to disk."""
        self._ports_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _utc_now(),
            "ports": self._ports,
        }
        tmp_path = self._ports_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self._ports_path)

    def reserve_port(
        self,
        name: str,
        preferred_port: int,
        bind_host: str = "127.0.0.1",
    ) -> int:
        """
        Reserve a port for a service.

        Algorithm:
        1. If we have a previously allocated port for this service, try to reuse it
        2. If that port is unavailable, try the preferred port
        3. If preferred port is unavailable, scan range [preferred, preferred+50)
        4. If all in range are busy, get any free port from OS
        5. Persist the selection

        Args:
            name: Service name (e.g., "prefect", "mlflow")
            preferred_port: Preferred port number
            bind_host: Host to bind to

        Returns:
            Selected port number
        """
        # Check if we have a previously allocated port
        previous_port = self._ports.get(name)
        if previous_port is not None:
            if is_port_available(previous_port, bind_host):
                return previous_port
            # Previous port no longer available, need to reallocate

        # Try the preferred port
        if is_port_available(preferred_port, bind_host):
            self._ports[name] = preferred_port
            self._save_ports()
            return preferred_port

        # Scan range for a free port
        range_end = preferred_port + self.PORT_RANGE_SIZE
        free_port = find_free_port_in_range(preferred_port, range_end, bind_host)
        if free_port is not None:
            self._ports[name] = free_port
            self._save_ports()
            return free_port

        # Fallback: let OS assign a port
        fallback_port = find_any_free_port(bind_host)
        self._ports[name] = fallback_port
        self._save_ports()
        return fallback_port

    def release_port(self, name: str) -> None:
        """
        Release a port reservation.

        Note: This removes the reservation from memory and disk,
        but does not unbind any actual sockets.

        Args:
            name: Service name
        """
        if name in self._ports:
            del self._ports[name]
            self._save_ports()

    def get_port(self, name: str) -> int | None:
        """
        Get the currently reserved port for a service.

        Args:
            name: Service name

        Returns:
            Port number if reserved, None otherwise
        """
        return self._ports.get(name)

    def get_all_ports(self) -> dict[str, int]:
        """Get all currently reserved ports."""
        return dict(self._ports)


# ─────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────


def reserve_port(
    data_dir: Path,
    name: str,
    preferred_port: int,
    bind_host: str = "127.0.0.1",
) -> int:
    """
    Reserve a port for a service (convenience function).

    Args:
        data_dir: OptAIC DATA_DIR
        name: Service name
        preferred_port: Preferred port number
        bind_host: Host to bind to

    Returns:
        Selected port number
    """
    manager = PortManager(data_dir)
    return manager.reserve_port(name, preferred_port, bind_host)


def load_reserved_ports(data_dir: Path) -> dict[str, int]:
    """Load all reserved ports from disk."""
    manager = PortManager(data_dir)
    return manager.get_all_ports()


# Default port assignments
DEFAULT_PORTS = {
    "api": 8080,
    "centrifugo": 8081,
    "redis": 6379,
    "prefect": 4200,
    "mlflow": 5000,
}
