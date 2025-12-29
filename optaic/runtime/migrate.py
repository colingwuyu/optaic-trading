from __future__ import annotations

from contextlib import contextmanager
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
import sys
from typing import Iterator

from alembic import command
from alembic.config import Config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_migration_paths(repo_root: Path | None = None) -> tuple[Path, Path]:
    root = repo_root or _repo_root()
    return root / "libs" / "db" / "alembic.ini", root / "libs" / "db" / "migrations"


def _package_root() -> Traversable | None:
    try:
        package_root = resources.files("libs.db")
    except Exception:
        return None
    alembic_ini = package_root / "alembic.ini"
    migrations = package_root / "migrations"
    if alembic_ini.is_file() and migrations.is_dir():
        return package_root
    return None


@contextmanager
def migration_paths(
    repo_root: Path | None = None,
) -> Iterator[tuple[Path, Path, Path | None]]:
    package_root = _package_root()
    if package_root is not None:
        alembic_ini = package_root / "alembic.ini"
        migrations = package_root / "migrations"
        with resources.as_file(alembic_ini) as config_path, resources.as_file(
            migrations
        ) as migrations_path:
            yield config_path, migrations_path, None
            return

    root = repo_root or _repo_root()
    config_path, migrations_path = resolve_migration_paths(root)
    yield config_path, migrations_path, root


def run_migrations(database_url: str, repo_root: Path | None = None) -> None:
    with migration_paths(repo_root) as (config_path, migrations_path, sys_path_root):
        if not config_path.exists():
            raise FileNotFoundError(f"Alembic config not found at {config_path}")
        if not migrations_path.exists():
            raise FileNotFoundError(f"Alembic migrations not found at {migrations_path}")

        if sys_path_root is not None and str(sys_path_root) not in sys.path:
            sys.path.insert(0, str(sys_path_root))

        alembic_cfg = Config(str(config_path))
        alembic_cfg.set_main_option("script_location", str(migrations_path))
        if sys_path_root is not None:
            alembic_cfg.set_main_option("prepend_sys_path", str(sys_path_root))
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)

        command.upgrade(alembic_cfg, "head")
