"""Tests for optaic.runtime.optional_deps module."""

from __future__ import annotations

import pytest

from optaic.runtime import optional_deps


def test_missing_dependency_error_message() -> None:
    """Test error message format."""
    err = optional_deps.MissingDependencyError("prefect", "prefect")
    assert "prefect" in str(err)
    assert "pip install 'optaic[prefect]'" in str(err)


def test_missing_dependency_error_with_feature() -> None:
    """Test error message with purpose description."""
    err = optional_deps.MissingDependencyError(
        "prefect", "prefect", purpose="Local Prefect server"
    )
    assert "Local Prefect server" in str(err)
    assert "pip install 'optaic[prefect]'" in str(err)


def test_require_package_success() -> None:
    """Test require_package succeeds for installed package."""
    # json is always available
    optional_deps.require_package("json", "server")  # Should not raise


def test_require_package_failure() -> None:
    """Test require_package fails for missing package."""
    with pytest.raises(optional_deps.MissingDependencyError) as exc_info:
        optional_deps.require_package("nonexistent_pkg_12345", "test")
    assert "nonexistent_pkg_12345" in str(exc_info.value)
    assert "pip install 'optaic[test]'" in str(exc_info.value)


def test_is_package_available_true() -> None:
    """Test is_package_available returns True for installed packages."""
    assert optional_deps.is_package_available("json")
    assert optional_deps.is_package_available("os")


def test_is_package_available_false() -> None:
    """Test is_package_available returns False for missing packages."""
    assert not optional_deps.is_package_available("nonexistent_pkg_12345")


def test_optional_import_success() -> None:
    """Test optional_import returns module for installed package."""
    result = optional_deps.optional_import("json")
    assert result is not None
    assert hasattr(result, "dumps")


def test_optional_import_failure() -> None:
    """Test optional_import returns None for missing package."""
    result = optional_deps.optional_import("nonexistent_pkg_12345")
    assert result is None


def test_require_fastapi() -> None:
    """Test require_fastapi helper."""
    # FastAPI should be available in dev environment
    optional_deps.require_fastapi()  # Should not raise


def test_require_sqlalchemy() -> None:
    """Test require_sqlalchemy helper."""
    # SQLAlchemy should be available in dev environment
    optional_deps.require_sqlalchemy()  # Should not raise
