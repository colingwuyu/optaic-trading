"""Tests for import profiles and optional dependency handling."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from optaic.runtime import optional_deps


# ─────────────────────────────────────────────────────────────
# Extras validation
# ─────────────────────────────────────────────────────────────


def test_pyproject_has_all_extras() -> None:
    """Test that pyproject.toml has all required extras."""
    import tomllib

    pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    extras = data["project"]["optional-dependencies"]

    # Required extras
    required = {"sdk", "client", "server", "realtime", "prefect", "mlflow",
                "redis", "storage", "engines", "all", "full", "dev"}

    assert required.issubset(set(extras.keys())), \
        f"Missing extras: {required - set(extras.keys())}"


def test_extras_client_is_alias_for_sdk() -> None:
    """Test that client extra has same deps as sdk."""
    import tomllib

    pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    extras = data["project"]["optional-dependencies"]
    assert set(extras["client"]) == set(extras["sdk"])


def test_extras_engines_has_prefect_and_mlflow() -> None:
    """Test that engines extra includes prefect and mlflow deps."""
    import tomllib

    pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    extras = data["project"]["optional-dependencies"]
    engines_deps = " ".join(extras["engines"])
    assert "prefect" in engines_deps
    assert "mlflow" in engines_deps


# ─────────────────────────────────────────────────────────────
# Import safety tests
# ─────────────────────────────────────────────────────────────


def test_optaic_import_succeeds() -> None:
    """Test that importing optaic succeeds."""
    import optaic
    assert optaic is not None


def test_optaic_runtime_import_succeeds() -> None:
    """Test that importing optaic.runtime modules succeeds."""
    from optaic.runtime import optional_deps as od
    assert od is not None


def test_optional_deps_require_returns_module() -> None:
    """Test require() returns the module."""
    import json
    result = optional_deps.require("json", "server", purpose="test")
    assert result is json


def test_optional_deps_require_raises_with_message() -> None:
    """Test require() raises MissingDependencyError with helpful message."""
    with pytest.raises(optional_deps.MissingDependencyError) as exc_info:
        optional_deps.require("nonexistent_xyz", "test", purpose="testing")

    msg = str(exc_info.value)
    assert "nonexistent_xyz" in msg
    assert "pip install 'optaic[test]'" in msg
    assert "testing" in msg


@pytest.mark.skipif(
    not optional_deps.is_package_available("prefect"),
    reason="prefect not installed"
)
def test_require_prefect_returns_module() -> None:
    """Test require_prefect returns prefect module when available."""
    prefect = optional_deps.require_prefect()
    assert prefect is not None
    assert hasattr(prefect, "flow")


@pytest.mark.skipif(
    not optional_deps.is_package_available("mlflow"),
    reason="mlflow not installed"
)
def test_require_mlflow_returns_module() -> None:
    """Test require_mlflow returns mlflow module when available."""
    mlflow = optional_deps.require_mlflow()
    assert mlflow is not None


def test_require_fastapi_returns_module() -> None:
    """Test require_fastapi returns fastapi module when available."""
    fastapi = optional_deps.require_fastapi()
    assert fastapi is not None
    assert hasattr(fastapi, "FastAPI")


def test_require_sqlalchemy_returns_module() -> None:
    """Test require_sqlalchemy returns sqlalchemy module when available."""
    sqlalchemy = optional_deps.require_sqlalchemy()
    assert sqlalchemy is not None


# ─────────────────────────────────────────────────────────────
# No heavy imports at top-level validation
# ─────────────────────────────────────────────────────────────


def test_optional_deps_module_has_no_heavy_imports() -> None:
    """Test that optional_deps.py itself doesn't import heavy deps at top-level."""
    import optaic.runtime.optional_deps

    source_file = Path(optaic.runtime.optional_deps.__file__)
    source = source_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    heavy_deps = {"prefect", "mlflow", "redis", "boto3", "fastapi", "sqlalchemy"}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in heavy_deps, \
                    f"optional_deps.py has top-level import of {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in heavy_deps, \
                f"optional_deps.py has top-level import from {node.module}"
