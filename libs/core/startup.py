"""Application Startup Hooks.

This module provides startup hooks that run when the application boots.
Key responsibilities:
- Seed built-in definitions (pipelines, stores, accessors, ops)
- Initialize system resources if needed
- Run any one-time setup tasks

The seed_definitions function is idempotent - it only creates definitions
that don't already exist, so it's safe to call on every startup.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


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


async def run_startup_hooks() -> None:
    """Run all startup hooks.

    This should be called during application lifespan startup.
    """
    logger.info("startup.hooks_starting")

    try:
        async with AsyncSessionLocal() as session:
            results = await seed_definitions_if_needed(session)

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

    except Exception as e:
        # Log but don't fail startup - definitions may already exist
        # or database may not be ready yet
        logger.warning(
            "startup.seeding_skipped",
            error=str(e),
            hint="Run 'optaic seed-definitions' manually if needed",
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
