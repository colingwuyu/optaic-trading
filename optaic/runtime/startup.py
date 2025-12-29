"""
Startup ordering and graceful shutdown for OptAIC services.

Defines the correct startup order for all services and ensures clean shutdown
on Ctrl+C or termination signals.

STARTUP ORDER:
1. Core DB migrations (OptAIC)
2. Engine DB migrations (Prefect/MLflow) if enabled local
3. Redis (optional, before Centrifugo if using redis engine)
4. Centrifugo
5. Prefect server + worker (optional)
6. MLflow server (optional)
7. API
8. Worker
9. Agent

SHUTDOWN ORDER: Reverse of startup.
"""

from __future__ import annotations

import atexit
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# Startup order definition
# ─────────────────────────────────────────────────────────────

# Services in startup order (first to start, last to stop)
STARTUP_ORDER: list[str] = [
    "db-migrations",      # 1. Core DB migrations
    "engine-migrations",  # 2. Engine DB migrations (Prefect/MLflow)
    "redis",              # 3. Redis (optional)
    "centrifugo",         # 4. Centrifugo
    "prefect-server",     # 5. Prefect server
    "prefect-worker",     # 6. Prefect worker
    "mlflow",             # 7. MLflow server
    "api",                # 8. API
    "worker",             # 9. Worker
    "agent",              # 10. Agent
]


@dataclass
class ServiceLifecycle:
    """Lifecycle definition for a service."""

    name: str
    start: Callable[[], bool] | None = None  # Returns True on success
    stop: Callable[[], None] | None = None
    is_started: bool = False
    startup_timeout: float = 30.0
    stop_timeout: float = 5.0
    optional: bool = False  # If true, failure doesn't stop startup


@dataclass
class StartupContext:
    """Context for a startup/shutdown sequence."""

    data_dir: Path
    started_services: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    shutdown_in_progress: bool = False


class StartupManager:
    """
    Manages ordered startup and shutdown of OptAIC services.

    Usage:
        mgr = StartupManager(data_dir)
        mgr.register_service("api", start_fn, stop_fn)
        mgr.register_service("worker", start_fn, stop_fn)

        if mgr.start_all():
            # All services started successfully
            mgr.wait_for_shutdown()
        else:
            # Some services failed, mgr already stopped everything
            pass
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._services: dict[str, ServiceLifecycle] = {}
        self._context = StartupContext(data_dir=data_dir)
        self._shutdown_registered = False

    def register_service(
        self,
        name: str,
        *,
        start: Callable[[], bool] | None = None,
        stop: Callable[[], None] | None = None,
        startup_timeout: float = 30.0,
        stop_timeout: float = 5.0,
        optional: bool = False,
    ) -> None:
        """
        Register a service for managed lifecycle.

        Args:
            name: Service name (should be in STARTUP_ORDER)
            start: Function to start the service (returns True on success)
            stop: Function to stop the service
            startup_timeout: Max time to wait for startup
            stop_timeout: Max time for graceful stop before kill
            optional: If True, failure doesn't abort startup
        """
        self._services[name] = ServiceLifecycle(
            name=name,
            start=start,
            stop=stop,
            startup_timeout=startup_timeout,
            stop_timeout=stop_timeout,
            optional=optional,
        )

    def start_all(self) -> bool:
        """
        Start all registered services in order.

        Returns:
            True if all required services started, False otherwise
        """
        self._register_shutdown_handlers()

        # Sort services by STARTUP_ORDER
        ordered_names = self._get_ordered_services()

        for name in ordered_names:
            service = self._services.get(name)
            if service is None:
                continue

            if service.start is None:
                # No start function, consider it already started
                service.is_started = True
                self._context.started_services.append(name)
                continue

            try:
                success = service.start()
                if success:
                    service.is_started = True
                    self._context.started_services.append(name)
                else:
                    error = f"Service {name} failed to start"
                    self._context.errors.append(error)
                    if not service.optional:
                        self._log_error(error)
                        self.stop_all()
                        return False
                    self._log_warning(f"{error} (optional, continuing)")
            except Exception as exc:
                error = f"Service {name} raised exception: {exc}"
                self._context.errors.append(error)
                if not service.optional:
                    self._log_error(error)
                    self.stop_all()
                    return False
                self._log_warning(f"{error} (optional, continuing)")

        return True

    def stop_all(self) -> None:
        """Stop all started services in reverse order."""
        if self._context.shutdown_in_progress:
            return
        self._context.shutdown_in_progress = True

        # Stop in reverse order
        for name in reversed(self._context.started_services):
            service = self._services.get(name)
            if service is None or not service.is_started:
                continue

            if service.stop is not None:
                try:
                    service.stop()
                except Exception as exc:
                    self._log_warning(f"Error stopping {name}: {exc}")

            service.is_started = False

        self._context.started_services.clear()
        self._context.shutdown_in_progress = False

    def is_running(self) -> bool:
        """Check if any services are running."""
        return len(self._context.started_services) > 0

    def get_started_services(self) -> list[str]:
        """Get list of currently started services."""
        return list(self._context.started_services)

    def get_errors(self) -> list[str]:
        """Get list of errors from startup."""
        return list(self._context.errors)

    # ─────────────────────────────────────────────────────────────
    # Signal handling
    # ─────────────────────────────────────────────────────────────

    def _register_shutdown_handlers(self) -> None:
        """Register atexit and signal handlers for graceful shutdown."""
        if self._shutdown_registered:
            return

        atexit.register(self.stop_all)

        # Handle SIGINT (Ctrl+C) and SIGTERM
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self._shutdown_registered = True

    def _signal_handler(self, signum: int, frame: object) -> None:
        """Handle shutdown signals."""
        self._log_info(f"Received signal {signum}, shutting down...")
        self.stop_all()
        sys.exit(0)

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _get_ordered_services(self) -> list[str]:
        """Get registered services sorted by STARTUP_ORDER."""
        result: list[str] = []
        for name in STARTUP_ORDER:
            if name in self._services:
                result.append(name)
        # Add any services not in STARTUP_ORDER at the end
        for name in self._services:
            if name not in result:
                result.append(name)
        return result

    def _log_info(self, message: str) -> None:
        """Log info message."""
        print(f"[startup] {_utc_now()} INFO: {message}", flush=True)

    def _log_warning(self, message: str) -> None:
        """Log warning message."""
        print(f"[startup] {_utc_now()} WARNING: {message}", flush=True)

    def _log_error(self, message: str) -> None:
        """Log error message."""
        print(f"[startup] {_utc_now()} ERROR: {message}", flush=True, file=sys.stderr)


# ─────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────


def create_startup_manager(data_dir: Path) -> StartupManager:
    """Create a StartupManager with standard configuration."""
    return StartupManager(data_dir)


def get_startup_order() -> list[str]:
    """Get the standard startup order."""
    return list(STARTUP_ORDER)


def get_shutdown_order() -> list[str]:
    """Get the standard shutdown order (reverse of startup)."""
    return list(reversed(STARTUP_ORDER))
