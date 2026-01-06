"""Application Startup Hooks.

This module provides startup hooks that run when the application boots.
Key responsibilities:
- Create database schema if needed (for embedded SQLite mode)
- Bootstrap system tenant, admin, and System Space
- Seed built-in definitions (pipelines, stores, accessors, ops)
- Initialize system resources if needed
- Run any one-time setup tasks

All operations are idempotent - safe to call on every startup.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


def ensure_schema_and_migrations() -> None:
    """Ensure database schema exists and migrations are applied.

    Strategy:
    1. Check if alembic_version table exists
       - If not: Fresh database - run alembic upgrade head (creates all tables)
       - If yes: Check if migrations are at head, skip if already up-to-date
    2. Handle nested event loop (when called from async context like FastAPI lifespan)

    This handles both development (fresh SQLite) and production (migrations).
    """
    from sqlalchemy import create_engine, inspect, text
    from libs.core.settings import get_settings

    settings = get_settings()
    db_url = settings.database_url

    # Convert async URL to sync for schema operations
    sync_url = db_url.replace("+aiosqlite", "").replace("+asyncpg", "")

    # Ensure directory exists for SQLite file
    if "sqlite" in sync_url and ":///" in sync_url:
        db_path = sync_url.split(":///", 1)[1]
        if db_path and not db_path.startswith(":memory:"):
            db_dir = Path(db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

    sync_engine = create_engine(sync_url, echo=False)

    try:
        # Check if alembic_version table exists (indicates migrations have run)
        inspector = inspect(sync_engine)
        tables = inspector.get_table_names()

        if "alembic_version" not in tables:
            logger.info("startup.fresh_database_detected")
            # Run Alembic upgrade to head for fresh database
            _run_alembic_upgrade(sync_url)
        else:
            # Check if already at head - skip if up-to-date
            # This avoids running Alembic from async context (nested event loop)
            with sync_engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version"))
                current_version = result.scalar()

            if current_version and _is_at_head(current_version):
                logger.info(
                    "startup.migrations_already_at_head", version=current_version
                )
            else:
                # Need to run migrations
                _run_alembic_upgrade(sync_url)

    finally:
        sync_engine.dispose()


def _is_at_head(current_version: str) -> bool:
    """Check if current migration version is at head.

    This is a lightweight check to avoid running Alembic unnecessarily,
    especially when called from async context (nested event loop issue).

    Returns True if we believe migrations are up-to-date based on:
    - Current version matches a known migration revision
    - The revision file exists and appears valid

    Note: This is an optimization to skip Alembic when migrations were
    already run (e.g., by e2e_server.py before starting API subprocess).
    For fresh databases or when pending migrations exist, Alembic will run.
    """
    from pathlib import Path
    import libs.db

    db_package_dir = Path(libs.db.__file__).parent
    versions_dir = db_package_dir / "migrations" / "versions"

    if not versions_dir.exists():
        return True  # No versions dir, assume OK

    # Check if the current version exists as a migration file
    # If we have the version file, assume migrations are applied
    for pyfile in versions_dir.glob("*.py"):
        if pyfile.name.startswith("_"):
            continue
        content = pyfile.read_text()
        if f'revision: str = "{current_version}"' in content:
            # Found the current version's migration file
            # Check if any other migration depends on this (has it as down_revision)
            # If none depend on it, it's likely the head
            is_head = True
            for other_file in versions_dir.glob("*.py"):
                if other_file == pyfile or other_file.name.startswith("_"):
                    continue
                other_content = other_file.read_text()
                if (
                    "down_revision" in other_content
                    and f'"{current_version}"' in other_content
                ):
                    # Another migration has this as down_revision, not at head
                    is_head = False
                    break
            return is_head

    return False


def _run_alembic_upgrade(db_url: str) -> None:
    """Run Alembic migrations to head.

    This applies any pending migrations, or creates all tables from scratch
    if this is a fresh database.
    """
    from alembic import command
    from alembic.config import Config

    # Find alembic.ini relative to libs/db/
    import libs.db

    db_package_dir = Path(libs.db.__file__).parent
    alembic_ini = db_package_dir / "alembic.ini"

    if not alembic_ini.exists():
        # Fallback: try project root
        project_root = Path(__file__).parent.parent.parent
        alembic_ini = project_root / "libs" / "db" / "alembic.ini"

    if not alembic_ini.exists():
        logger.warning(
            "startup.alembic_ini_not_found",
            searched=str(alembic_ini),
            hint="Falling back to metadata.create_all()",
        )
        _fallback_create_all(db_url)
        return

    try:
        alembic_cfg = Config(str(alembic_ini))
        # Override database URL from settings
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        # Set script location relative to alembic.ini
        alembic_cfg.set_main_option(
            "script_location", str(alembic_ini.parent / "migrations")
        )

        logger.info("startup.running_migrations")
        command.upgrade(alembic_cfg, "head")
        logger.info("startup.migrations_complete")

    except Exception as e:
        logger.warning(
            "startup.migration_failed",
            error=str(e),
            hint="Falling back to metadata.create_all()",
        )
        _fallback_create_all(db_url)


def _fallback_create_all(db_url: str) -> None:
    """Fallback: Create all tables via SQLAlchemy metadata.

    Used when Alembic isn't available or fails.
    """
    from sqlalchemy import create_engine
    from libs.db.base import Base
    import libs.db.models  # noqa: F401 - Register all models

    logger.info("startup.creating_schema_fallback")
    sync_engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    logger.info("startup.schema_created")


async def seed_definitions_if_needed(session: AsyncSession) -> dict[str, int]:
    """Seed built-in definitions if they don't exist.

    This function is idempotent - it only creates definitions that don't
    already exist in the database.

    Args:
        session: Database session

    Returns:
        Dict with counts of seeded items by type
    """
    from scripts.seed_definitions import seed_all_definitions

    return await seed_all_definitions(session)


async def load_uploaded_plugins(session: AsyncSession) -> int:
    """Load all uploaded definition plugins into FactoryRegistry.

    This enables users to create Instances from uploaded Definitions.
    Plugins are loaded by:
    1. Adding artifact path to sys.path
    2. Importing the module file
    3. Registering the class in the appropriate factory

    Args:
        session: Database session

    Returns:
        Number of plugins loaded
    """
    from libs.core.plugin_loader import load_all_plugins

    return await load_all_plugins(session)


async def run_startup_hooks() -> None:
    """Run all startup hooks.

    This should be called during application lifespan startup.

    Order of operations:
    1. Ensure database schema exists (SQLite only)
    2. Bootstrap system (tenant, admin, System Space) - idempotent
    3. Seed definitions (pipelines, stores, accessors, ops) - idempotent
    4. Load uploaded plugins (register in FactoryRegistry)
    """
    logger.info("startup.hooks_starting")

    try:
        # 0. Ensure schema exists and migrations are applied
        ensure_schema_and_migrations()

        async with AsyncSessionLocal() as session:
            # 1. Bootstrap system (idempotent)
            from libs.core.bootstrap import bootstrap_system

            bootstrap_result = await bootstrap_system(session)

            if bootstrap_result.created:
                logger.info(
                    "startup.system_bootstrapped",
                    tenant_id=str(bootstrap_result.tenant_id),
                    admin_id=str(bootstrap_result.admin_principal_id),
                    space_id=str(bootstrap_result.system_space_id),
                )

            # 2. Seed definitions (uses System Project as parent)
            results = await seed_definitions_if_needed(session)

            # Commit all changes
            await session.commit()

            total = sum(results.values())
            if total > 0:
                logger.info(
                    "startup.definitions_seeded",
                    pipelines=results.get("pipelines", 0),
                    stores=results.get("stores", 0),
                    accessors=results.get("accessors", 0),
                    ops=results.get("ops", 0),
                    total=total,
                )
            else:
                logger.info("startup.definitions_already_exist")

            # 3. Load uploaded plugins (register in FactoryRegistry)
            plugin_count = await load_uploaded_plugins(session)
            if plugin_count > 0:
                logger.info("startup.plugins_loaded", count=plugin_count)

    except Exception as e:
        # Log but don't fail startup - bootstrap/definitions may already exist
        # or database may not be ready yet
        logger.warning(
            "startup.hooks_failed",
            error=str(e),
            hint="Run 'optaic bootstrap' manually if needed",
        )

    logger.info("startup.hooks_completed")


async def ensure_system_tenant_exists(session: AsyncSession) -> None:
    """Ensure the system tenant exists.

    The system tenant owns built-in definitions and provides
    a namespace for system-level resources.

    Args:
        session: Database session
    """
    from uuid import UUID

    from sqlalchemy import select

    from libs.db.models.resource import Resource

    SYSTEM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

    # Check if system tenant root resource exists
    stmt = select(Resource).where(
        Resource.tenant_id == SYSTEM_TENANT_ID,
        Resource.type == "TenantRoot",
    )
    result = await session.scalars(stmt)
    existing = result.first()

    if existing:
        return

    # Create system tenant root if needed
    logger.info("startup.creating_system_tenant")

    root = Resource(
        id=UUID("00000000-0000-0000-0000-000000000010"),
        tenant_id=SYSTEM_TENANT_ID,
        type="TenantRoot",
        name="System",
        owner_principal_id=UUID("00000000-0000-0000-0000-000000000003"),
        space_kind="system",
        subspace_kind="official",
        status="active",
    )
    session.add(root)

    # Create system space
    space = Resource(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        tenant_id=SYSTEM_TENANT_ID,
        type="Space",
        parent_id=root.id,
        name="System Definitions",
        owner_principal_id=UUID("00000000-0000-0000-0000-000000000003"),
        space_kind="system",
        subspace_kind="official",
        status="active",
    )
    session.add(space)
    await session.commit()
