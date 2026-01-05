"""Seed Built-in Definitions for Quant Domain.

This script populates the database with system-provided Definition resources
that reference factory-registered implementations in libs/data/.

The code_ref field in each Definition points to a key in the corresponding factory:
- PipelineDefinition.code_ref -> PIPELINE_FACTORY[code_ref]
- StoreDefinition.code_ref -> STORE_FACTORY[code_ref]
- AccessorDefinition.code_ref -> ACCESSOR_FACTORY[code_ref]
- OpDefinition.code_ref -> OPS_REGISTRY[code_ref]

Run this script on first boot or after migrations to ensure built-in definitions exist.

Usage:
    python scripts/seed_definitions.py
    # Or via CLI:
    optaic seed-definitions
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from libs.db.session import AsyncSessionLocal  # noqa: E402
from libs.db.models.resource import Resource  # noqa: E402
from libs.db.models.quant import (  # noqa: E402
    PipelineDefinition,
    StoreDefinition,
    AccessorDefinition,
    OpDefinition,
)

# Import well-known system IDs from bootstrap module
# These are created by bootstrap_system() on first startup
from libs.core.bootstrap import (  # noqa: E402
    SYSTEM_TENANT_ID,
    SYSTEM_PRINCIPAL_ID,
    SYSTEM_PROJECT_ID,
)

# Parent for all definitions is the System Project (inside Official subspace)
SYSTEM_DEFINITIONS_PARENT_ID = SYSTEM_PROJECT_ID

# =============================================================================
# Built-in Definitions
# =============================================================================

# These code_ref values MUST match the keys registered in libs/data/ factories

BUILT_IN_PIPELINES: list[dict[str, Any]] = [
    {
        "name": "ExpressionPipeline",
        "code_ref": "ExpressionPipeline",
        "category": "expression",
        "description": "Execute expressions on existing datasets",
        "interface_spec": "libs.data.pipelines.base.DataPipeline",
    },
    {
        "name": "FredPipeline",
        "code_ref": "FredPipeline",
        "category": "etl",
        "description": "Fetch economic data from FRED API",
        "interface_spec": "libs.data.pipelines.base.DataPipeline",
    },
    {
        "name": "BloombergPipeline",
        "code_ref": "BloombergPipeline",
        "category": "etl",
        "description": "Fetch market data from Bloomberg terminal",
        "interface_spec": "libs.data.pipelines.base.DataPipeline",
    },
    {
        "name": "OHLCVBloombergPipeline",
        "code_ref": "OHLCVBloombergPipeline",
        "category": "etl",
        "description": "Fetch OHLCV data from Bloomberg with preset fields",
        "interface_spec": "libs.data.pipelines.base.DataPipeline",
    },
    {
        "name": "SQLiteUpdatePipeline",
        "code_ref": "SQLiteUpdatePipeline",
        "category": "etl",
        "description": "Update SQLite database from source files",
        "interface_spec": "libs.data.pipelines.base.DataPipeline",
    },
]

BUILT_IN_STORES: list[dict[str, Any]] = [
    {
        "name": "ParquetStore",
        "code_ref": "ParquetStore",
        "backend_type": "parquet",
        "description": "Column-oriented Parquet file storage",
        "interface_spec": "libs.data.store.base.BaseStore",
    },
    {
        "name": "SQLiteStore",
        "code_ref": "SQLiteStore",
        "backend_type": "sqlite",
        "description": "SQLite database storage",
        "interface_spec": "libs.data.store.base.BaseStore",
    },
    {
        "name": "VirtualStore",
        "code_ref": "VirtualStore",
        "backend_type": "virtual",
        "description": "In-memory virtual storage for computed datasets",
        "interface_spec": "libs.data.store.base.BaseStore",
    },
    {
        "name": "FlatFileStore",
        "code_ref": "FlatFileStore",
        "backend_type": "flatfile",
        "description": "Read from CSV, Excel, Parquet flat files",
        "interface_spec": "libs.data.store.base.BaseStore",
    },
    {
        "name": "ConfigStore",
        "code_ref": "ConfigStore",
        "backend_type": "config",
        "description": "Read-only YAML/JSON configuration files",
        "interface_spec": "libs.data.store.base.BaseStore",
    },
]

BUILT_IN_ACCESSORS: list[dict[str, Any]] = [
    {
        "name": "SimpleAccessor",
        "code_ref": "SimpleAccessor",
        "accessor_type": "simple",
        "description": "Basic time-range and column filtering",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
    {
        "name": "PITAccessor",
        "code_ref": "PITAccessor",
        "accessor_type": "pit",
        "description": "Point-in-time filtering for avoiding lookahead bias",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
    {
        "name": "EconomicsAccessor",
        "code_ref": "EconomicsAccessor",
        "accessor_type": "pit",
        "description": "Vintage-aware economic data access with revision support",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
    {
        "name": "FieldsAccessor",
        "code_ref": "FieldsAccessor",
        "accessor_type": "field",
        "description": "Multi-field data access (OHLCV)",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
    {
        "name": "TickerAccessor",
        "code_ref": "TickerAccessor",
        "accessor_type": "ticker",
        "description": "Multi-ticker data access",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
    {
        "name": "GenericFuturesAccessor",
        "code_ref": "GenericFuturesAccessor",
        "accessor_type": "futures",
        "description": "Futures contract roll and continuous series",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
    {
        "name": "UniverseSearchAccessor",
        "code_ref": "UniverseSearchAccessor",
        "accessor_type": "search",
        "description": "Search and filter universe of tickers",
        "interface_spec": "libs.data.access.base.BaseAccessor",
    },
]

# Operators from OPS_REGISTRY
BUILT_IN_OPS: list[dict[str, Any]] = [
    # Time Series
    {
        "name": "REF",
        "code_ref": "REF",
        "category": "time_series",
        "signature": "REF(data, n=1)",
    },
    {
        "name": "DELTA",
        "code_ref": "DELTA",
        "category": "time_series",
        "signature": "DELTA(data, n=1)",
    },
    {
        "name": "TS_CONCAT",
        "code_ref": "TS_CONCAT",
        "category": "time_series",
        "signature": "TS_CONCAT(*args)",
    },
    {
        "name": "TS_RANK",
        "code_ref": "TS_RANK",
        "category": "time_series",
        "signature": "TS_RANK(data, window)",
    },
    {
        "name": "TS_ZSCORE",
        "code_ref": "TS_ZSCORE",
        "category": "time_series",
        "signature": "TS_ZSCORE(data, window)",
    },
    {
        "name": "TS_SUM",
        "code_ref": "TS_SUM",
        "category": "time_series",
        "signature": "TS_SUM(data, window)",
    },
    {
        "name": "TS_PRODUCT",
        "code_ref": "TS_PRODUCT",
        "category": "time_series",
        "signature": "TS_PRODUCT(data, window)",
    },
    {
        "name": "TS_ARGMAX",
        "code_ref": "TS_ARGMAX",
        "category": "time_series",
        "signature": "TS_ARGMAX(data, window)",
    },
    {
        "name": "TS_ARGMIN",
        "code_ref": "TS_ARGMIN",
        "category": "time_series",
        "signature": "TS_ARGMIN(data, window)",
    },
    {
        "name": "DECAY_LINEAR",
        "code_ref": "DECAY_LINEAR",
        "category": "time_series",
        "signature": "DECAY_LINEAR(data, window)",
    },
    {
        "name": "DECAY_EXP",
        "code_ref": "DECAY_EXP",
        "category": "time_series",
        "signature": "DECAY_EXP(data, halflife)",
    },
    # Statistics
    {
        "name": "MEAN",
        "code_ref": "MEAN",
        "category": "statistics",
        "signature": "MEAN(data, window)",
    },
    {
        "name": "STD",
        "code_ref": "STD",
        "category": "statistics",
        "signature": "STD(data, window)",
    },
    {
        "name": "CORR",
        "code_ref": "CORR",
        "category": "statistics",
        "signature": "CORR(x, y, window)",
    },
    {
        "name": "BETA",
        "code_ref": "BETA",
        "category": "statistics",
        "signature": "BETA(y, x, window)",
    },
    {
        "name": "MAX",
        "code_ref": "MAX",
        "category": "statistics",
        "signature": "MAX(data, window)",
    },
    {
        "name": "MIN",
        "code_ref": "MIN",
        "category": "statistics",
        "signature": "MIN(data, window)",
    },
    # Math
    {"name": "LOG", "code_ref": "LOG", "category": "math", "signature": "LOG(data)"},
    {"name": "ABS", "code_ref": "ABS", "category": "math", "signature": "ABS(data)"},
    {"name": "SIGN", "code_ref": "SIGN", "category": "math", "signature": "SIGN(data)"},
    {"name": "ADD", "code_ref": "ADD", "category": "math", "signature": "ADD(a, b)"},
    {"name": "SUB", "code_ref": "SUB", "category": "math", "signature": "SUB(a, b)"},
    {"name": "MUL", "code_ref": "MUL", "category": "math", "signature": "MUL(a, b)"},
    {"name": "DIV", "code_ref": "DIV", "category": "math", "signature": "DIV(a, b)"},
    {
        "name": "CUMRET",
        "code_ref": "CUMRET",
        "category": "math",
        "signature": "CUMRET(returns)",
    },
    {
        "name": "COMBINE",
        "code_ref": "COMBINE",
        "category": "math",
        "signature": "COMBINE(*args)",
    },
    # PIT
    {
        "name": "VALUES",
        "code_ref": "VALUES",
        "category": "pit",
        "signature": "VALUES(data, col='value')",
    },
    {
        "name": "DROP_META",
        "code_ref": "DROP_META",
        "category": "pit",
        "signature": "DROP_META(data)",
    },
    {
        "name": "AS_OF_DATE",
        "code_ref": "AS_OF_DATE",
        "category": "pit",
        "signature": "AS_OF_DATE(data, as_of)",
    },
    # Futures
    {
        "name": "ROLL_FUTURES",
        "code_ref": "ROLL_FUTURES",
        "category": "futures",
        "signature": "ROLL_FUTURES(contracts, roll_days=5)",
    },
    {
        "name": "FUTURES_UNIVERSE",
        "code_ref": "FUTURES_UNIVERSE",
        "category": "futures",
        "signature": "FUTURES_UNIVERSE(root, include_expired=False)",
    },
]


# =============================================================================
# Seeding Functions
# =============================================================================


async def _resource_exists(
    session: AsyncSession, tenant_id: UUID, name: str, resource_type: str
) -> UUID | None:
    """Check if a resource with given name and type already exists."""
    stmt = select(Resource).where(
        Resource.tenant_id == tenant_id,
        Resource.name == name,
        Resource.type == resource_type,
    )
    result = await session.scalars(stmt)
    existing = result.first()
    return existing.id if existing else None


async def seed_pipeline_definitions(session: AsyncSession) -> int:
    """Seed built-in pipeline definitions."""
    count = 0
    for pipeline in BUILT_IN_PIPELINES:
        existing_id = await _resource_exists(
            session, SYSTEM_TENANT_ID, pipeline["name"], "PipelineDef"
        )
        if existing_id:
            continue

        resource_id = uuid4()
        resource = Resource(
            id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            type="PipelineDef",
            parent_id=SYSTEM_DEFINITIONS_PARENT_ID,
            owner_principal_id=SYSTEM_PRINCIPAL_ID,
            name=pipeline["name"],
            space_kind="system",
            subspace_kind="official",
            status="active",
            metadata_json={"description": pipeline.get("description", "")},
        )
        session.add(resource)
        await session.flush()  # Flush Resource before Definition (FK dependency)

        definition = PipelineDefinition(
            resource_id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            category=pipeline["category"],
            interface_spec=pipeline["interface_spec"],
            code_ref=pipeline["code_ref"],
            input_schema={},
            output_schema={},
            parameters_schema={},
            compatibility_rules={},
            guardrail_contracts=[],
        )
        session.add(definition)
        count += 1

    await session.flush()
    return count


async def seed_store_definitions(session: AsyncSession) -> int:
    """Seed built-in store definitions."""
    count = 0
    for store in BUILT_IN_STORES:
        existing_id = await _resource_exists(
            session, SYSTEM_TENANT_ID, store["name"], "StoreDef"
        )
        if existing_id:
            continue

        resource_id = uuid4()
        resource = Resource(
            id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            type="StoreDef",
            parent_id=SYSTEM_DEFINITIONS_PARENT_ID,
            owner_principal_id=SYSTEM_PRINCIPAL_ID,
            name=store["name"],
            space_kind="system",
            subspace_kind="official",
            status="active",
            metadata_json={"description": store.get("description", "")},
        )
        session.add(resource)
        await session.flush()  # Flush Resource before Definition (FK dependency)

        definition = StoreDefinition(
            resource_id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            backend_type=store["backend_type"],
            interface_spec=store["interface_spec"],
            code_ref=store["code_ref"],
            parameters_schema={},
            guardrail_contracts=[],
        )
        session.add(definition)
        count += 1

    await session.flush()
    return count


async def seed_accessor_definitions(session: AsyncSession) -> int:
    """Seed built-in accessor definitions."""
    count = 0
    for accessor in BUILT_IN_ACCESSORS:
        existing_id = await _resource_exists(
            session, SYSTEM_TENANT_ID, accessor["name"], "AccessorDef"
        )
        if existing_id:
            continue

        resource_id = uuid4()
        resource = Resource(
            id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            type="AccessorDef",
            parent_id=SYSTEM_DEFINITIONS_PARENT_ID,
            owner_principal_id=SYSTEM_PRINCIPAL_ID,
            name=accessor["name"],
            space_kind="system",
            subspace_kind="official",
            status="active",
            metadata_json={"description": accessor.get("description", "")},
        )
        session.add(resource)
        await session.flush()  # Flush Resource before Definition (FK dependency)

        definition = AccessorDefinition(
            resource_id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            accessor_type=accessor["accessor_type"],
            interface_spec=accessor["interface_spec"],
            code_ref=accessor["code_ref"],
            parameters_schema={},
            guardrail_contracts=[],
        )
        session.add(definition)
        count += 1

    await session.flush()
    return count


async def seed_op_definitions(session: AsyncSession) -> int:
    """Seed built-in operator definitions."""
    count = 0
    for op in BUILT_IN_OPS:
        existing_id = await _resource_exists(
            session, SYSTEM_TENANT_ID, op["name"], "OpDef"
        )
        if existing_id:
            continue

        resource_id = uuid4()
        resource = Resource(
            id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            type="OpDef",
            parent_id=SYSTEM_DEFINITIONS_PARENT_ID,
            owner_principal_id=SYSTEM_PRINCIPAL_ID,
            name=op["name"],
            space_kind="system",
            subspace_kind="official",
            status="active",
            metadata_json={},
        )
        session.add(resource)
        await session.flush()  # Flush Resource before Definition (FK dependency)

        definition = OpDefinition(
            resource_id=resource_id,
            tenant_id=SYSTEM_TENANT_ID,
            category=op["category"],
            signature=op["signature"],
            interface_spec="libs.data.ops.core.Operator",
            code_ref=op["code_ref"],
            input_schema={},
            output_schema={},
            parameters_schema={},
        )
        session.add(definition)
        count += 1

    await session.flush()
    return count


async def seed_all_definitions(session: AsyncSession) -> dict[str, int]:
    """Seed all built-in definitions.

    Note: Caller is responsible for committing the session.
    This allows callers to batch multiple operations before committing.
    """
    results = {
        "pipelines": await seed_pipeline_definitions(session),
        "stores": await seed_store_definitions(session),
        "accessors": await seed_accessor_definitions(session),
        "ops": await seed_op_definitions(session),
    }
    await session.flush()
    return results


async def main() -> None:
    """Run seeding standalone.

    When running as a script, this function handles:
    1. Bootstrap (if needed)
    2. Seeding definitions
    3. Committing all changes
    """
    import structlog

    structlog.configure(
        processors=[
            structlog.dev.ConsoleRenderer(),
        ],
    )
    logger = structlog.get_logger()

    logger.info("Starting definition seeding...")

    async with AsyncSessionLocal() as session:
        # Bootstrap first (creates system tenant, space, project)
        from libs.core.bootstrap import bootstrap_system

        bootstrap_result = await bootstrap_system(session)
        if bootstrap_result.created:
            logger.info(
                "System bootstrapped",
                tenant_id=str(bootstrap_result.tenant_id),
            )

        # Seed definitions
        results = await seed_all_definitions(session)

        # Commit all changes
        await session.commit()

    logger.info(
        "Seeding complete",
        pipelines=results["pipelines"],
        stores=results["stores"],
        accessors=results["accessors"],
        ops=results["ops"],
        total=sum(results.values()),
    )


if __name__ == "__main__":
    asyncio.run(main())
