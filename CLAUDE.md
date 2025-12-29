# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OptAIC is a resource management and activity tracking platform with an embedded web UI and Windows-friendly runtime. It provides a unified API for resources, chat, real-time updates, and audit trails. The system ships a single `optaic` CLI that boots API + worker + agent + Centrifugo and serves the React UI.

## Development Commands

```bash
# Install dependencies (recommended)
uv venv
uv pip install -e . --group dev

# Run the full stack (embedded mode)
optaic server
optaic server --with-prefect --with-mlflow  # with local engines

# Run tests
pytest                                      # all tests
pytest apps/api/tests/test_resources.py     # single file
pytest -k test_create_resource              # single test

# Linting and formatting
ruff check .                                # lint
ruff format .                               # format
mypy .                                      # type check

# Database migrations
make migrate desc="add new field"           # create migration
make upgrade                                # apply migrations
make downgrade                              # rollback one step

# Docker development
make dev-deps                               # start postgres, redis, minio, centrifugo
make dev-api                                # run API with hot reload on port 8081
docker compose -f infra/docker-compose.yml up --build  # full stack

# Build
make build                                  # build webui + wheel
make build-webui                            # build React UI only
```

## Architecture

### Monorepo Structure
- **optaic/**: Distributable CLI package + runtime supervisor
- **apps/api/**: FastAPI application (serves UI, issues realtime tokens)
- **apps/worker/**: Outbox consumer (publishes to Centrifugo, handles notifications)
- **apps/agent/**: LLM agent runner (activity-driven)
- **apps/web/**: React SPA frontend
- **libs/core/**: Domain models, RBAC (PyCasbin), activity envelope, settings
- **libs/db/**: SQLAlchemy models, session management, Alembic migrations
- **libs/sdk_py/**: Python SDK client

### Key Patterns

**Everything is a Resource**: All entities (Space, Project, Dataset, Channel, Message, etc.) are stored in the `resources` table with type discrimination. Resources form hierarchies via `parent_id` and can be connected via `resource_edges`.

**Activity-Driven System**: Every action creates an Activity record. The outbox table queues activities for async processing by the worker, which publishes to Centrifugo for real-time updates.

**Multi-Tenant RBAC**: PyCasbin for policy-based access control. Role bindings are scoped to resources and inherit up the hierarchy via `parent_id`.

**Versioning**: Resources support Git-like branching via `resource_versions` (content history) and `resource_refs` (branches/tags). Merge requests and promotion requests enable workflow control.

**Async-First**: All database operations use async SQLAlchemy (asyncpg for Postgres, aiosqlite for SQLite).

### Entry Points
- CLI: `optaic/cli.py` → `optaic` command
- API: `apps/api/main.py` → FastAPI app
- Worker: `apps/worker/main.py` → outbox consumer
- Agent: `apps/agent/main.py` → activity-driven agent

### Configuration
- Core settings: `libs/core/settings.py`
- Database: `libs/db/` (engine, session, migrations)
- Migrations: `libs/db/alembic.ini`

## Tech Stack

- Python 3.11+, FastAPI, async SQLAlchemy, Alembic
- SQLite (embedded) / PostgreSQL (prod)
- Centrifugo (real-time WebSocket)
- React 18, Vite, Zustand, Tailwind CSS
- PyCasbin (RBAC), structlog (logging)

## Testing

Tests use pytest with pytest-asyncio in auto mode. Test files are in each package's `tests/` directory:
- `libs/core/tests/`
- `libs/db/tests/`
- `apps/api/tests/`
- `apps/worker/tests/`
- `apps/agent/tests/`
- `optaic/tests/`

## VSCode Debugging

Launch configurations are provided in `.vscode/launch.json`:
- **API: debug** - FastAPI on port 8081
- **Worker: debug** - Outbox consumer
- **Agent: debug** - Activity-driven agent
- **OptAIC server: debug** - Full stack supervisor

Initialize the SQLite schema before debugging individual services:
```powershell
optaic upgrade --apply
```
