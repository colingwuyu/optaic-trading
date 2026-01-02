# File Mapping: optaic-v0 → optaic-trading

Complete mapping of source files to target locations.

## Data Platform Core

| Source (optaic-v0) | Target (optaic-trading) | Notes |
|-------------------|------------------------|-------|
| `dev_tools/src/data/api.py` | `libs/data/api.py` | DataAPI adapted for Resource model |
| `dev_tools/src/data/catalog.py` | `libs/data/catalog.py` | DatasetInfo, enums |
| `dev_tools/src/data/registry.py` | `libs/data/registry.py` | Factory registries |

## Storage Layer

| Source | Target | Notes |
|--------|--------|-------|
| `dev_tools/src/data/store/base.py` | `libs/data/store/base.py` | BaseStore ABC |
| `dev_tools/src/data/store/parquet.py` | `libs/data/store/parquet.py` | ParquetStore |
| `dev_tools/src/data/store/sqlite.py` | `libs/data/store/sqlite.py` | SQLiteStore |
| `dev_tools/src/data/store/virtual.py` | `libs/data/store/virtual.py` | VirtualStore |

## Accessor Layer

| Source | Target | Notes |
|--------|--------|-------|
| `dev_tools/src/data/access/base.py` | `libs/data/access/base.py` | BaseAccessor |
| `dev_tools/src/data/access/simple.py` | `libs/data/access/simple.py` | SimpleAccessor |
| `dev_tools/src/data/access/pit.py` | `libs/data/access/pit.py` | PITAccessor |

## Expressions & Operators

| Source | Target | Notes |
|--------|--------|-------|
| `dev_tools/src/function/expression.py` | `libs/data/expression.py` | Expression engine |
| `dev_tools/src/function/ops.py` | `libs/data/ops.py` | Operator registry |

## Pipelines

| Source | Target | Notes |
|--------|--------|-------|
| `dev_tools/src/pipelines/expression.py` | `libs/data/pipelines/expression.py` | ExpressionPipeline |
| `dev_tools/src/pipelines/fred.py` | `libs/data/pipelines/etl/fred.py` | FRED data |
| `dev_tools/src/pipelines/bloomberg.py` | `libs/data/pipelines/etl/bloomberg.py` | Bloomberg data |

## UI Components (Phase 6)

| Source | Target | Notes |
|--------|--------|-------|
| `dev_tools/src/ui/next_app/` | `apps/web/` | Entire Next.js app |
| `dev_tools/src/ui/api.py` | Reference only | Study for API router patterns |

## Key Adaptation Rules

1. **Imports**: Add tenant isolation and async patterns
2. **Returns**: Never return SQLAlchemy models - use DTOs
3. **Errors**: Replace generic exceptions with FastAPI HTTPException
4. **State**: Replace in-memory state with database queries
