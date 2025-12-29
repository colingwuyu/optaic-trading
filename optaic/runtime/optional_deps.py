"""
Optional dependency guards for graceful import failures.

Provides clear error messages when optional dependencies are missing,
directing users to install the appropriate extras.

Usage:
    from optaic.runtime.optional_deps import require_prefect

    prefect = require_prefect()     # Returns module or raises clear error
    prefect.flow(...)               # Now safe to use
"""

from __future__ import annotations

import importlib
from types import ModuleType


class MissingDependencyError(RuntimeError):
    """Raised when an optional dependency is not installed."""

    def __init__(self, package: str, extra: str, *, purpose: str | None = None):
        self.package = package
        self.extra = extra
        self.purpose = purpose

        if purpose:
            msg = f"Missing optional dependency '{package}' needed for {purpose}."
        else:
            msg = f"Missing dependency '{package}'."
        msg += f"\n\nInstall with:\n  pip install 'optaic[{extra}]'"
        super().__init__(msg)


def require(
    pkg_name: str,
    extra: str,
    purpose: str | None = None,
) -> ModuleType:
    """
    Require a package, returning the module or raising a helpful error.

    Args:
        pkg_name: The package to import (e.g., 'prefect', 'mlflow')
        extra: The extras name to suggest (e.g., 'prefect', 'all')
        purpose: Optional description of what needs this package

    Returns:
        The imported module

    Raises:
        MissingDependencyError: If the package cannot be imported

    Example:
        prefect = require('prefect', 'prefect', purpose='Local Prefect server')
        prefect.flow(...)  # Now safe
    """
    try:
        return importlib.import_module(pkg_name)
    except ImportError as exc:
        raise MissingDependencyError(pkg_name, extra, purpose=purpose) from exc


def require_package(
    pkg_name: str,
    extra_hint: str,
    *,
    feature: str | None = None,
) -> None:
    """
    Ensure a package is installed (legacy interface, raises but returns nothing).

    Args:
        pkg_name: The package to import
        extra_hint: The extras name to suggest
        feature: Optional feature description for error message

    Raises:
        MissingDependencyError: If the package cannot be imported
    """
    require(pkg_name, extra_hint, purpose=feature)


def is_package_available(pkg_name: str) -> bool:
    """
    Check if a package is available without raising an error.

    Args:
        pkg_name: The package to check

    Returns:
        True if the package can be imported, False otherwise
    """
    try:
        importlib.import_module(pkg_name)
        return True
    except ImportError:
        return False


# ─────────────────────────────────────────────────────────────
# Convenience functions for common optional dependencies
# ─────────────────────────────────────────────────────────────


def require_prefect() -> ModuleType:
    """Require Prefect for local orchestration. Returns prefect module."""
    return require("prefect", "prefect", purpose="Local Prefect server")


def require_mlflow() -> ModuleType:
    """Require MLflow for local experiment tracking. Returns mlflow module."""
    return require("mlflow", "mlflow", purpose="Local MLflow server")


def require_redis_client() -> ModuleType:
    """Require Redis Python client. Returns redis module."""
    return require("redis", "redis", purpose="Redis client")


def require_fastapi() -> ModuleType:
    """Require FastAPI for server mode. Returns fastapi module."""
    return require("fastapi", "server", purpose="OptAIC server")


def require_sqlalchemy() -> ModuleType:
    """Require SQLAlchemy for database access. Returns sqlalchemy module."""
    return require("sqlalchemy", "server", purpose="Database access")


def require_boto3() -> ModuleType:
    """Require boto3 for S3/cloud storage. Returns boto3 module."""
    return require("boto3", "storage", purpose="Cloud storage (S3)")


# ─────────────────────────────────────────────────────────────
# Conditional import helper
# ─────────────────────────────────────────────────────────────


def optional_import(pkg_name: str) -> ModuleType | None:
    """
    Import a package if available, returning None if not.

    Args:
        pkg_name: The package to import

    Returns:
        The imported module or None if not available
    """
    try:
        return importlib.import_module(pkg_name)
    except ImportError:
        return None
