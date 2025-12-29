#!/usr/bin/env python
"""
Check for forbidden top-level imports in specific packages.

This script enforces the "no heavy imports at import-time" rule to ensure
selective extras installs don't break import-time.

Rules:
- optaic/sdk: forbid fastapi, sqlalchemy, prefect, mlflow, redis
- optaic/runtime: forbid prefect, mlflow, redis at module top-level
  (they should only be imported inside functions/methods)

Usage:
    python scripts/check_optional_imports.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple


class ImportViolation(NamedTuple):
    """A forbidden import violation."""
    file: Path
    line: int
    module: str
    reason: str


# Heavy dependencies that should be guarded
HEAVY_DEPS = {"prefect", "mlflow", "redis", "boto3"}
SERVER_DEPS = {"fastapi", "uvicorn", "sqlalchemy", "alembic"}

# Rules by package path pattern
RULES: dict[str, set[str]] = {
    # SDK should not import any server or engine deps
    "optaic/sdk": HEAVY_DEPS | SERVER_DEPS,
    # libs/sdk_py should not import any server or engine deps
    "libs/sdk_py": HEAVY_DEPS | SERVER_DEPS,
}

# Modules that should never have heavy deps at top-level
# (must import inside functions only)
LAZY_IMPORT_REQUIRED: dict[str, set[str]] = {
    "optaic/runtime": HEAVY_DEPS,
}


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to find top-level imports."""

    def __init__(self) -> None:
        self.imports: list[tuple[int, str]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # Get root module (e.g., 'prefect' from 'prefect.flows')
            root = alias.name.split(".")[0]
            self.imports.append((node.lineno, root))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            self.imports.append((node.lineno, root))


def check_file(file_path: Path, forbidden: set[str]) -> list[ImportViolation]:
    """Check a single file for forbidden imports."""
    violations = []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return violations

    visitor = ImportVisitor()
    visitor.visit(tree)

    for lineno, module in visitor.imports:
        if module in forbidden:
            violations.append(ImportViolation(
                file=file_path,
                line=lineno,
                module=module,
                reason=f"Forbidden top-level import of '{module}'",
            ))

    return violations


def check_lazy_imports(file_path: Path, heavy_deps: set[str]) -> list[ImportViolation]:
    """
    Check that heavy deps are only imported inside functions, not at top-level.

    Returns violations for any top-level imports of heavy deps.
    """
    violations = []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return violations

    # Only check top-level statements (not inside functions/classes)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in heavy_deps:
                        violations.append(ImportViolation(
                            file=file_path,
                            line=node.lineno,
                            module=root,
                            reason=f"'{root}' must be imported inside functions, not at top-level",
                        ))
            elif node.module:
                root = node.module.split(".")[0]
                if root in heavy_deps:
                    violations.append(ImportViolation(
                        file=file_path,
                        line=node.lineno,
                        module=root,
                        reason=f"'{root}' must be imported inside functions, not at top-level",
                    ))

    return violations


def find_python_files(directory: Path) -> list[Path]:
    """Find all Python files in a directory."""
    return list(directory.rglob("*.py"))


def main() -> int:
    """Run the import checker."""
    repo_root = Path(__file__).parent.parent
    all_violations: list[ImportViolation] = []

    # Check forbidden imports by package
    for pattern, forbidden in RULES.items():
        package_dir = repo_root / pattern
        if not package_dir.exists():
            continue

        for py_file in find_python_files(package_dir):
            violations = check_file(py_file, forbidden)
            all_violations.extend(violations)

    # Check lazy import requirements
    for pattern, heavy_deps in LAZY_IMPORT_REQUIRED.items():
        package_dir = repo_root / pattern
        if not package_dir.exists():
            continue

        for py_file in find_python_files(package_dir):
            violations = check_lazy_imports(py_file, heavy_deps)
            all_violations.extend(violations)

    # Report results
    if all_violations:
        print(f"Found {len(all_violations)} import violation(s):\n")
        for v in all_violations:
            rel_path = v.file.relative_to(repo_root)
            print(f"  {rel_path}:{v.line}: {v.reason}")
        print("\nTo fix: Move these imports inside functions that use them,")
        print("or guard them with 'from optaic.runtime.optional_deps import require_*'")
        return 1
    else:
        print("✓ No import violations found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
