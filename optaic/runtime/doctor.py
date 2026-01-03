"""
OptAIC Doctor - Comprehensive system diagnostics.

Provides actionable diagnostics for troubleshooting:
- DATA_DIR and configuration
- Core DB schema version
- Engine modes and DB paths
- Service health with log hints
- Port collision detection
- Stale pidfile cleanup
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from optaic.runtime.health import (
    check_service_health,
    tcp_check,
)
from optaic.runtime.ports import is_port_available
from optaic.runtime.service_manager import cleanup_stale_pids, get_service_status
from optaic.runtime.runtime_config import RuntimeConfig


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# Diagnostic result types
# ─────────────────────────────────────────────────────────────


@dataclass
class DiagnosticItem:
    """Single diagnostic check result."""

    name: str
    status: Literal["ok", "warn", "error", "info"]
    message: str
    details: str | None = None
    suggestion: str | None = None


@dataclass
class DoctorReport:
    """Complete doctor report."""

    data_dir: str
    checked_at: str
    items: list[DiagnosticItem] = field(default_factory=list)
    services: dict[str, dict] = field(default_factory=dict)
    engines: dict[str, dict] = field(default_factory=dict)

    def has_errors(self) -> bool:
        return any(item.status == "error" for item in self.items)

    def has_warnings(self) -> bool:
        return any(item.status == "warn" for item in self.items)


# ─────────────────────────────────────────────────────────────
# Core diagnostic functions
# ─────────────────────────────────────────────────────────────


def run_doctor(
    config: RuntimeConfig,
    *,
    auto_clean_stale_pids: bool = True,
    verbose: bool = False,
) -> DoctorReport:
    """
    Run comprehensive system diagnostics.

    Args:
        config: RuntimeConfig
        auto_clean_stale_pids: Auto-remove stale pidfiles
        verbose: Include extra details

    Returns:
        DoctorReport with all diagnostics
    """
    data_dir = config.data_dir
    report = DoctorReport(
        data_dir=str(data_dir),
        checked_at=_utc_now(),
    )

    # 1. DATA_DIR check
    report.items.append(_check_data_dir(data_dir))

    # 2. Core DB schema
    report.items.append(_check_core_db(config))

    # 3. Engines diagnostics
    engines_items, engines_info = _check_engines(config)
    report.items.extend(engines_items)
    report.engines = engines_info

    # 4. Services diagnostics
    services_items, services_info = _check_services(config)
    report.items.extend(services_items)
    report.services = services_info

    # 5. Port collision check
    report.items.extend(_check_port_collisions(config))

    # 6. Stale pidfile check
    report.items.extend(_check_stale_pids(data_dir, auto_clean=auto_clean_stale_pids))

    # 7. Last migration info
    report.items.extend(_check_last_migration(data_dir))

    return report


def _check_data_dir(data_dir: Path) -> DiagnosticItem:
    """Check DATA_DIR exists and is writable."""
    if not data_dir.exists():
        return DiagnosticItem(
            name="DATA_DIR",
            status="error",
            message=f"DATA_DIR does not exist: {data_dir}",
            suggestion="Run 'optaic init' to create the data directory.",
        )

    try:
        test_file = data_dir / ".doctor_test"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        return DiagnosticItem(
            name="DATA_DIR",
            status="ok",
            message=str(data_dir),
        )
    except Exception as exc:
        return DiagnosticItem(
            name="DATA_DIR",
            status="error",
            message=f"DATA_DIR not writable: {data_dir}",
            details=str(exc),
        )


def _check_core_db(config: RuntimeConfig) -> DiagnosticItem:
    """Check core DB schema version."""
    # This would need actual Alembic integration
    return DiagnosticItem(
        name="Core DB",
        status="info",
        message="Schema check requires running migrations",
        suggestion="Run 'optaic db upgrade' to ensure schema is current.",
    )


def _check_engines(
    config: RuntimeConfig,
) -> tuple[list[DiagnosticItem], dict[str, dict]]:
    """Check engine configurations and state."""
    items: list[DiagnosticItem] = []
    engines: dict[str, dict] = {}

    # Prefect
    prefect_mode = config.prefect.mode
    engines["prefect"] = {
        "enabled": config.prefect.enabled,
        "mode": prefect_mode,
        "port": config.prefect.port if config.prefect.is_local_mode else None,
        "url": config.prefect.effective_api_url,
    }

    if config.prefect.enabled:
        if prefect_mode == "local":
            db_path = config.data_dir / "engines" / "prefect" / "prefect.db"
            engines["prefect"]["db_path"] = str(db_path)
            items.append(
                DiagnosticItem(
                    name="Prefect Engine",
                    status="ok" if db_path.exists() else "warn",
                    message=f"Local mode on port {config.prefect.port}",
                    details=f"DB: {db_path}"
                    + (" (exists)" if db_path.exists() else " (not created)"),
                )
            )
        else:
            items.append(
                DiagnosticItem(
                    name="Prefect Engine",
                    status="ok",
                    message=f"Remote mode: {config.prefect.api_url}",
                )
            )
    else:
        items.append(
            DiagnosticItem(
                name="Prefect Engine",
                status="info",
                message="Disabled",
            )
        )

    # MLflow
    mlflow_mode = config.mlflow.mode
    engines["mlflow"] = {
        "enabled": config.mlflow.enabled,
        "mode": mlflow_mode,
        "port": config.mlflow.port if config.mlflow.is_local_mode else None,
        "url": config.mlflow.effective_tracking_uri,
    }

    if config.mlflow.enabled:
        if mlflow_mode == "local":
            # Parse backend store URI for sqlite path
            backend_uri = config.mlflow.backend_store_uri
            db_path = None
            if backend_uri.startswith("sqlite:///"):
                db_path = Path(backend_uri.replace("sqlite:///", "", 1))
            engines["mlflow"]["db_path"] = str(db_path) if db_path else backend_uri

            items.append(
                DiagnosticItem(
                    name="MLflow Engine",
                    status="ok" if (db_path and db_path.exists()) else "warn",
                    message=f"Local mode on port {config.mlflow.port}",
                    details=f"DB: {db_path or backend_uri}",
                )
            )
        else:
            items.append(
                DiagnosticItem(
                    name="MLflow Engine",
                    status="ok",
                    message=f"Remote mode: {config.mlflow.tracking_uri}",
                )
            )
    else:
        items.append(
            DiagnosticItem(
                name="MLflow Engine",
                status="info",
                message="Disabled",
            )
        )

    return items, engines


def _check_services(
    config: RuntimeConfig,
) -> tuple[list[DiagnosticItem], dict[str, dict]]:
    """Check service health and provide log hints on failure."""
    items: list[DiagnosticItem] = []
    services: dict[str, dict] = {}
    data_dir = config.data_dir
    logs_dir = data_dir / "logs"

    service_checks = [
        (
            "prefect-server",
            config.prefect.enabled and config.prefect.is_local_mode,
            "127.0.0.1",
            config.prefect.port,
        ),
        (
            "mlflow",
            config.mlflow.enabled and config.mlflow.is_local_mode,
            "127.0.0.1",
            config.mlflow.port,
        ),
    ]

    for name, enabled, host, port in service_checks:
        if not enabled:
            services[name] = {"status": "disabled"}
            continue

        health = check_service_health(name, host=host, port=port, enabled=True)
        services[name] = {
            "status": health.status,
            "port": port,
            "url": health.url,
        }

        if health.status == "up":
            items.append(
                DiagnosticItem(
                    name=f"Service: {name}",
                    status="ok",
                    message=f"Running on port {port}",
                    details=health.url,
                )
            )
        else:
            log_file = logs_dir / f"{name}.log"
            log_hint = _get_log_tail(log_file, lines=30)

            items.append(
                DiagnosticItem(
                    name=f"Service: {name}",
                    status="error",
                    message=f"Not responding on port {port}",
                    details=f"Last log lines:\n{log_hint}"
                    if log_hint
                    else "No log file found",
                    suggestion=f"Check log file: {log_file}"
                    if log_file.exists()
                    else "Service may not have started",
                )
            )

    return items, services


def _check_port_collisions(config: RuntimeConfig) -> list[DiagnosticItem]:
    """Detect port collisions and suggest remediation."""
    items: list[DiagnosticItem] = []

    ports_to_check = []
    if config.prefect.enabled and config.prefect.is_local_mode:
        ports_to_check.append(("Prefect", config.prefect.port))
    if config.mlflow.enabled and config.mlflow.is_local_mode:
        ports_to_check.append(("MLflow", config.mlflow.port))

    for name, port in ports_to_check:
        # Check if port is in use but service is not responding
        if not is_port_available(port, "127.0.0.1"):
            # Port is bound - this is expected if service is running
            if not tcp_check("127.0.0.1", port):
                items.append(
                    DiagnosticItem(
                        name=f"Port Collision: {name}",
                        status="warn",
                        message=f"Port {port} is bound but not responding",
                        suggestion=f"Check if another process is using port {port}. Use 'netstat -ano | findstr {port}' to identify.",
                    )
                )

    return items


def _check_stale_pids(
    data_dir: Path, *, auto_clean: bool = True
) -> list[DiagnosticItem]:
    """Check for and optionally clean stale pidfiles."""
    items: list[DiagnosticItem] = []

    if auto_clean:
        cleaned = cleanup_stale_pids(data_dir)
        if cleaned:
            items.append(
                DiagnosticItem(
                    name="Stale PIDs",
                    status="warn",
                    message=f"Cleaned {len(cleaned)} stale pidfile(s)",
                    details=", ".join(cleaned),
                )
            )
        else:
            items.append(
                DiagnosticItem(
                    name="Stale PIDs",
                    status="ok",
                    message="No stale pidfiles found",
                )
            )
    else:
        # Just detect without cleaning
        pids_dir = data_dir / "state" / "pids"
        if pids_dir.exists():
            stale = []
            for pidfile in pids_dir.glob("*.pid"):
                status = get_service_status(data_dir, pidfile.stem)
                if status.status == "stopped":
                    stale.append(pidfile.stem)

            if stale:
                items.append(
                    DiagnosticItem(
                        name="Stale PIDs",
                        status="warn",
                        message=f"Found {len(stale)} stale pidfile(s)",
                        details=", ".join(stale),
                        suggestion="Run 'optaic doctor --clean' to remove stale pidfiles",
                    )
                )

    return items


def _check_last_migration(data_dir: Path) -> list[DiagnosticItem]:
    """Check last engine migration time and backup location."""
    items: list[DiagnosticItem] = []
    state_path = data_dir / "engines" / "engines_state.json"

    if not state_path.exists():
        items.append(
            DiagnosticItem(
                name="Engine Migrations",
                status="info",
                message="No engine state recorded",
                suggestion="Migrations will run on first startup with local engines",
            )
        )
        return items

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))

        for engine in ["prefect", "mlflow"]:
            engine_state = state.get(engine, {})
            if not engine_state:
                continue

            last_migration = engine_state.get("last_migration_at")
            backup_path = engine_state.get("last_backup_path")
            version = engine_state.get("package_version")

            details = []
            if version:
                details.append(f"Version: {version}")
            if last_migration:
                details.append(f"Last migration: {last_migration}")
            if backup_path:
                details.append(f"Backup: {backup_path}")

            items.append(
                DiagnosticItem(
                    name=f"Engine State: {engine.title()}",
                    status="ok",
                    message=f"Version {version or 'unknown'}",
                    details="\n".join(details) if details else None,
                )
            )

    except Exception as exc:
        items.append(
            DiagnosticItem(
                name="Engine State",
                status="warn",
                message=f"Could not read engine state: {exc}",
            )
        )

    return items


def _get_log_tail(log_file: Path, lines: int = 30) -> str | None:
    """Get last N lines of a log file."""
    if not log_file.exists():
        return None

    try:
        content = log_file.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()
        return "\n".join(all_lines[-lines:])
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Output formatting
# ─────────────────────────────────────────────────────────────


def format_doctor_report(report: DoctorReport, *, color: bool = True) -> str:
    """Format doctor report for terminal output."""
    lines: list[str] = []

    # Status icons
    icons = {
        "ok": "✓" if color else "[OK]",
        "warn": "⚠" if color else "[WARN]",
        "error": "✗" if color else "[ERROR]",
        "info": "ℹ" if color else "[INFO]",
    }

    lines.append("=" * 60)
    lines.append("OptAIC Doctor Report")
    lines.append("=" * 60)
    lines.append(f"DATA_DIR: {report.data_dir}")
    lines.append(f"Checked: {report.checked_at}")
    lines.append("")

    # Group items by status
    for item in report.items:
        icon = icons.get(item.status, "?")
        lines.append(f"{icon} {item.name}: {item.message}")
        if item.details:
            for detail_line in item.details.split("\n"):
                lines.append(f"    {detail_line}")
        if item.suggestion:
            lines.append(f"    → {item.suggestion}")

    lines.append("")
    lines.append("=" * 60)

    # Summary
    errors = sum(1 for i in report.items if i.status == "error")
    warnings = sum(1 for i in report.items if i.status == "warn")

    if errors:
        lines.append(f"RESULT: {errors} error(s), {warnings} warning(s)")
    elif warnings:
        lines.append(f"RESULT: OK with {warnings} warning(s)")
    else:
        lines.append("RESULT: All checks passed")

    return "\n".join(lines)


def print_doctor_report(report: DoctorReport, *, color: bool = True) -> None:
    """Print doctor report to stdout."""
    print(format_doctor_report(report, color=color))
