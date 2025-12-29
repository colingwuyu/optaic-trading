"""Tests for optaic.runtime.startup module."""

from __future__ import annotations

from pathlib import Path

import pytest

from optaic.runtime import startup


def test_startup_order_defined() -> None:
    """Test that STARTUP_ORDER is defined correctly."""
    order = startup.STARTUP_ORDER
    assert len(order) > 0
    assert "api" in order
    assert "db-migrations" in order
    # db-migrations should be first
    assert order.index("db-migrations") < order.index("api")


def test_get_startup_order() -> None:
    """Test get_startup_order returns a copy."""
    order1 = startup.get_startup_order()
    order2 = startup.get_startup_order()
    assert order1 == order2
    assert order1 is not order2  # Should be a copy


def test_get_shutdown_order() -> None:
    """Test shutdown order is reverse of startup."""
    startup_order = startup.get_startup_order()
    shutdown_order = startup.get_shutdown_order()
    assert shutdown_order == list(reversed(startup_order))


def test_startup_manager_register_service(tmp_path: Path) -> None:
    """Test registering a service."""
    mgr = startup.StartupManager(tmp_path)
    mgr.register_service("api", start=lambda: True, stop=lambda: None)
    assert "api" in mgr._services


def test_startup_manager_start_success(tmp_path: Path) -> None:
    """Test successful startup."""
    mgr = startup.StartupManager(tmp_path)
    started = []
    mgr.register_service("api", start=lambda: (started.append("api"), True)[1])
    mgr.register_service("worker", start=lambda: (started.append("worker"), True)[1])

    success = mgr.start_all()
    assert success
    assert "api" in started
    assert "worker" in started


def test_startup_manager_start_failure_stops_all(tmp_path: Path) -> None:
    """Test that failure stops all previously started services."""
    mgr = startup.StartupManager(tmp_path)
    stopped = []

    mgr.register_service(
        "api",
        start=lambda: True,
        stop=lambda: stopped.append("api"),
    )
    mgr.register_service(
        "worker",
        start=lambda: False,  # Fails
    )

    success = mgr.start_all()
    assert not success
    assert "api" in stopped  # Should have been stopped


def test_startup_manager_optional_service_failure(tmp_path: Path) -> None:
    """Test optional service failure doesn't abort startup."""
    mgr = startup.StartupManager(tmp_path)

    mgr.register_service("redis", start=lambda: False, optional=True)
    mgr.register_service("api", start=lambda: True)

    success = mgr.start_all()
    assert success  # Should succeed despite redis failure


def test_startup_manager_stop_all_reverse_order(tmp_path: Path) -> None:
    """Test stop_all stops in reverse order."""
    mgr = startup.StartupManager(tmp_path)
    stopped = []

    mgr.register_service(
        "db-migrations",
        start=lambda: True,
        stop=lambda: stopped.append("db-migrations"),
    )
    mgr.register_service(
        "api",
        start=lambda: True,
        stop=lambda: stopped.append("api"),
    )

    mgr.start_all()
    mgr.stop_all()

    # api should be stopped before db-migrations (reverse order)
    assert stopped == ["api", "db-migrations"]


def test_startup_manager_get_started_services(tmp_path: Path) -> None:
    """Test getting list of started services."""
    mgr = startup.StartupManager(tmp_path)
    mgr.register_service("api", start=lambda: True)

    assert mgr.get_started_services() == []
    mgr.start_all()
    assert mgr.get_started_services() == ["api"]


def test_startup_manager_is_running(tmp_path: Path) -> None:
    """Test is_running check."""
    mgr = startup.StartupManager(tmp_path)
    mgr.register_service("api", start=lambda: True)

    assert not mgr.is_running()
    mgr.start_all()
    assert mgr.is_running()
    mgr.stop_all()
    assert not mgr.is_running()


def test_create_startup_manager(tmp_path: Path) -> None:
    """Test convenience function."""
    mgr = startup.create_startup_manager(tmp_path)
    assert mgr.data_dir == tmp_path


def test_startup_manager_ordered_by_startup_order(tmp_path: Path) -> None:
    """Test services start in STARTUP_ORDER."""
    mgr = startup.StartupManager(tmp_path)
    started = []

    # Register in wrong order
    mgr.register_service("api", start=lambda: (started.append("api"), True)[1])
    mgr.register_service(
        "db-migrations",
        start=lambda: (started.append("db-migrations"), True)[1],
    )

    mgr.start_all()

    # db-migrations should start before api
    assert started.index("db-migrations") < started.index("api")
