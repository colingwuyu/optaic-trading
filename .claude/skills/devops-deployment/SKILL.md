---
name: devops-deployment
description: Follow these patterns when developing, testing, packaging, or deploying OptAIC. Use for understanding the native Windows deployment model (wheel-based, no Docker), Artifactory lanes strategies, and avoiding container anti-patterns.
---

# OptAIC DevOps & Deployment Model

Follow these patterns when developing, testing, packaging, or deploying OptAIC. This skill ensures agents understand the project's native Windows deployment model and avoid anti-patterns like Docker-based solutions.

## Critical Context

**OptAIC is a native Windows application** distributed as a Python wheel. There is NO Docker in production. All infrastructure (API, worker, agent, Centrifugo, Redis, databases) runs natively on Windows systems.

## Architecture Overview

(See original file for architecture diagram - omitted here for brevity)

## Anti-Patterns (DO NOT DO)

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| Docker Compose for deployment | Production is native Windows |
| Dockerfile for testing | Use local wheel install instead |
| PostgreSQL container tests | Use SQLite for embedded tests |
| Rebuilding Artifactory scripts | Already complete in 'infra/artifactory/' |
| External service dependencies | Self-contained binaries managed by CLI |
| Manual database migrations | Auto-run on 'optaic server' startup |
| Strict Foreign Keys in Audit Logs | Audit logs must survive broken references |

## Correct Patterns

### 1. Wheel Packaging Structure

The project is packaged via 'pyproject.toml' with modular extras.
(See original file)

### 2. Build & Publish Pipeline

Use 'uv build' and provided scripts.

### 3. Artifactory Lanes (Windows pypiserver)

(See original file)

### 4. Installation Patterns

**Development:**
'''bash
uv venv && uv pip install -e .[dev]
optaic server
'''

### 5. Database Auto-Migration

Migrations run automatically via Alembic on startup.

### 6. Testing Patterns

**Unit tests (no external dependencies):**
'''bash
uv run pytest libs/db/tests/        # SQLite in-memory
uv run pytest libs/core/tests/      # Pure Python
'''

**Test fixtures use SQLite (no Docker) with proper configuration:**
'''python
# libs/db/tests/conftest.py pattern
@pytest_asyncio.fixture(scope='session')
async def test_engine():
    # Use NullPool to avoid file locks
    engine = create_async_engine(url, poolclass=NullPool)
    
    # Important: Set pragmas for performance and loose audit coupling
    @event.listens_for(Pool, 'connect')
    def _set_sqlite_pragmas(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA foreign_keys=OFF') # Vital for audit logging resilience
        cursor.close()
        
    yield engine
'''

### 7. Self-Upgrade Pattern

(See original file)

### 8. Configuration (Environment-Driven)

'DATABASE_URL=sqlite:///data.db' or postgresql.

### 9. Binary Management

Managed via 'optaic/infra/versions.json'.

