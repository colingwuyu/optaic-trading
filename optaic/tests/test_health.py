"""Tests for optaic.runtime.health module."""

from __future__ import annotations

import http.server
import socket
import threading


from optaic.runtime import health


def test_tcp_check_open_port() -> None:
    """Test TCP check on an open port."""
    # Create a listening socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        assert health.tcp_check("127.0.0.1", port, timeout=1.0)


def test_tcp_check_closed_port() -> None:
    """Test TCP check on a closed port."""
    # Find a port that's likely not in use
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Port is now closed
    assert not health.tcp_check("127.0.0.1", port, timeout=0.5)


def test_http_check_success() -> None:
    """Test HTTP check with successful response."""

    # Start a simple HTTP server
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format, *args):
            pass  # Suppress logging

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    assert health.http_check(f"http://127.0.0.1:{port}/", expect_status=(200,))
    server.server_close()


def test_http_check_failure() -> None:
    """Test HTTP check with connection refused."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # No server running
    assert not health.http_check(f"http://127.0.0.1:{port}/")


def test_check_service_health_disabled() -> None:
    """Test health check for disabled service."""
    result = health.check_service_health("api", enabled=False)
    assert result.status == "disabled"


def test_check_service_health_no_port() -> None:
    """Test health check with missing port."""
    result = health.check_service_health("api", port=None)
    assert result.status == "error"
    assert "Port not configured" in (result.error or "")


def test_check_service_health_down() -> None:
    """Test health check for service that's down."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Port is closed
    result = health.check_service_health("api", port=port)
    assert result.status == "down"
    assert result.port == port


def test_service_health_dataclass() -> None:
    """Test ServiceHealth dataclass fields."""
    h = health.ServiceHealth(
        name="test",
        status="up",
        pid=1234,
        port=8080,
        url="http://localhost:8080/",
    )
    assert h.name == "test"
    assert h.status == "up"
    assert h.pid == 1234
    assert h.port == 8080


def test_get_security_warnings_localhost() -> None:
    """Test no warnings for localhost bindings."""
    warnings = health.get_security_warnings(
        {"api": "127.0.0.1", "prefect": "127.0.0.1"}
    )
    assert len(warnings) == 0


def test_get_security_warnings_all_interfaces() -> None:
    """Test warnings for 0.0.0.0 bindings."""
    warnings = health.get_security_warnings({"api": "0.0.0.0", "prefect": "127.0.0.1"})
    assert len(warnings) == 1
    assert "api" in warnings[0]
    assert "0.0.0.0" in warnings[0]


def test_check_prefect_worker_health_no_pid() -> None:
    """Test worker health check with no PID."""
    assert not health.check_prefect_worker_health(None)


def test_check_prefect_worker_health_with_pid() -> None:
    """Test worker health check with current process PID."""
    import os

    # Current process should be alive
    assert health.check_prefect_worker_health(os.getpid())
