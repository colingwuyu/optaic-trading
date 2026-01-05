# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## CRITICAL: Native Windows Deployment Model

**OptAIC is deployed as a native Windows application via Python wheel.** There is NO Docker in production.

| Aspect | Implementation |
|--------|---------------|
| **Packaging** | Single Python wheel with extras (`pip install optaic[server]`) |
| **Distribution** | Local Artifactory with lanes: staging → uat → prod |
| **Deployment** | `pip install` + `optaic server` on Windows Server |
| **Testing** | SQLite fixtures, no containers required |
| **Database** | SQLite (embedded) or PostgreSQL (external) |
| **Binaries** | Centrifugo/Redis auto-downloaded by CLI |

**Read the `devops-deployment` skill for complete DevOps patterns.**

### Anti-Patterns (DO NOT DO)

- Using Docker for testing (use SQLite fixtures)
- Rebuilding Artifactory scripts (already complete in `infra/artifactory/`)
- Adding Docker dependencies to production code (use native Windows embedded deployment model)
- Manual database migrations (auto-run on `optaic server`)

## Unit Test Requirements Policy

### All Tasks Must Pass Unit Tests
The agent must ensure that all code implementations and resulting tasks, excluding pure documentation updates, have passing unit tests before reporting completion to the user.

- **Pre-report verification:** Always run the project's test suite as a final step.
- **Do not proceed if tests fail:** If tests fail, the agent must troubleshoot and fix the failures before considering the task complete.

### Zero Warnings Policy
All tests must not only pass, but also execute without any warnings (e.g., deprecation warnings, linting warnings, compiler warnings).

- **Warning Resolution:** If any warnings occur during the test run or compilation, the agent is responsible for resolving them as if they were errors.
- **Clean Output:** The final report to the user must confirm that the test output is entirely clean of warnings and errors.

### NO MOCKS Policy (CRITICAL)
Mocks are NOT allowed for internal application logic. Use real database sessions and ORM models.

| Instead of... | Use... |
|---------------|--------|
| `AsyncMock(spec=Service)` | Real service with `db_session` fixture |
| `MagicMock(spec=AsyncSession)` | Real `db_session` from conftest.py |
| Raw SQL for test data | ORM model instances |

**Only exception:** External third-party APIs (Bloomberg, vendor APIs).

### Test Anti-Patterns (FORBIDDEN)

| Anti-Pattern | Why It's Wrong | Correct Approach |
|--------------|----------------|------------------|
| `def test_x(): pass` | Fake test, inflates count | Remove or implement real test |
| `try: ... except: pass` | Hides failures | Let exceptions propagate |
| `except ImportError: pass` | Silent skip of broken deps | **Fix pyproject.toml** |

### Dependency Policy

**All imports must be in pyproject.toml.** If a test imports a package:
- The package MUST be listed in `[project.dependencies]` or `[dependency-groups.dev]`
- Import errors should FAIL tests loudly - they indicate broken project setup
- `pytest.importorskip()` is NOT an excuse for missing dependencies

Tests are meant to **discover errors**, not just make test counts go up.

## E2E Testing Architecture (CRITICAL)

E2E tests run against a **separate full-stack backend server**, NOT using ASGI transport in-process.

### How E2E Testing Works

1. **Start the E2E Server** first (VS Code: "E2E: Full Stack Server" or `python scripts/e2e_server.py`)
2. The server runs on port 8082 with its own SQLite database at `.tmp/optaic-e2e-data/`
3. E2E tests connect to `http://localhost:8082` via the Python SDK
4. Database migrations auto-run on server startup

### E2E Test Setup Pattern

```python
# tests/e2e/test_*.py
import os
import pytest
from libs.sdk_py import AsyncPlatformClient

E2E_API_URL = os.environ.get("E2E_API_URL", "http://localhost:8082")

@pytest_asyncio.fixture
async def client():
    client = AsyncPlatformClient(base_url=E2E_API_URL)
    yield client
    await client.close()
```

### Anti-Patterns (DO NOT DO)

| Anti-Pattern | Why It's Wrong | Correct Approach |
|--------------|----------------|------------------|
| `ASGITransport(app=app)` | In-process testing, no real HTTP | Connect to external server |
| Creating db_session fixtures | Tests shouldn't touch DB directly | Use SDK only |
| Mocking HTTP responses | Defeats E2E purpose | Use real server |

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `E2E_API_URL` | `http://localhost:8082` | Backend server URL |
| `E2E_API_PORT` | `8082` | Server port |
| `DATABASE_URL` | `.tmp/optaic-e2e-data/db/optaic.sqlite` | E2E database |

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

```
optaic-trading/
├── optaic/           # Distributable CLI package + runtime supervisor
├── apps/
│   ├── api/          # FastAPI application (serves UI, issues realtime tokens)
│   ├── worker/       # Outbox consumer (publishes to Centrifugo)
│   ├── agent/        # LLM agent runner (activity-driven)
│   └── web/          # React SPA frontend
├── libs/
│   ├── core/         # Domain models, RBAC, activity envelope, settings
│   ├── db/           # SQLAlchemy models, Alembic migrations
│   ├── sdk_py/       # Python SDK client
│   └── sdk_ts/       # TypeScript SDK client
├── .claude/
│   ├── agents/       # Claude Code specialized agents
│   └── skills/       # Claude Code skill definitions
├── .agent/
│   ├── rules/        # Agentic rules
│   └── workflows/    # Agentic workflows
├── infra/            # Docker, Centrifugo, deployment configs
├── scripts/          # Build, release, and utility scripts
└── docs/             # Documentation
```

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

## Authentication

OptAIC supports multiple authentication methods with priority-based fallback:

| Priority | Method | Header/Cookie | Use Case |
|----------|--------|---------------|----------|
| 1 | API Key | `X-API-Key: optaic_xxx.secret` | SDK clients, automation |
| 2 | OAuth/OIDC | `Authorization: Bearer <JWT>` | Azure AD SSO (production) |
| 3 | Session Cookie | `optaic_session` cookie | Web GUI login |
| 4 | Dev Headers | `X-Principal-Id` + `X-Tenant-Id` | Development only |

### SDK Authentication

```python
# API Key authentication (recommended for SDK)
client = AsyncPlatformClient(
    base_url="http://localhost:8081",
    api_key="optaic_abc123.secretkey...",
)

# Dev mode authentication (testing only)
client = AsyncPlatformClient(
    base_url="http://localhost:8081",
)
client.set_principal_id(principal_id)
client.set_tenant_id(tenant_id)
```

### Auth Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/keys` | POST | Create API key |
| `/auth/keys` | GET | List API keys |
| `/auth/keys/{id}` | DELETE | Revoke API key |
| `/auth/me` | GET | Get current user info |
| `/auth/login` | POST | Session login (dev mode) |
| `/auth/logout` | POST | Session logout |
| `/auth/register` | POST | Create local credential (dev mode) |

### Key Files

- `libs/core/auth.py` - AuthService (API keys, sessions, OIDC)
- `libs/db/models/auth.py` - APIKey, LocalCredential models
- `apps/api/routers/auth.py` - Auth API endpoints
- `apps/api/deps.py` - Multi-auth dependency flow
- `libs/sdk_py/client.py` - AuthClient for SDK

## Tech Stack

- Python 3.11+, FastAPI, async SQLAlchemy, Alembic
- SQLite (embedded) / PostgreSQL (prod)
- Centrifugo (real-time WebSocket)
- React 18, Vite, Zustand, Tailwind CSS
- PyCasbin (RBAC), structlog (logging)

## Framework Compliance (IMPORTANT)

**After completing any implementation task**, you MUST verify code follows OptAIC framework patterns.

### Required Patterns Checklist

| Component | Required Pattern |
|-----------|-----------------|
| Service mutations | Emit `ActivityEnvelope` via `record_activity_with_outbox()` |
| Service create/update | Call `GuardrailsEngine.validate_at_gate()` |
| API handlers | Return Pydantic DTOs, NOT SQLAlchemy models |
| API handlers | Do NOT emit activities (service layer does this) |
| Data pipelines | Include `knowledge_date` for PIT correctness |
| SDK extensions | Use lazy imports for heavy deps (pandas, numpy) |

### Compliance Workflow

1. Complete implementation
2. **Run compliance review** using one of these agents:
   - `optaic-compliance-reviewer` - Full review + test generation
   - `pre-commit-reviewer` - Pre-commit checks (lint, security, tests)
3. Fix any violations
4. Generate framework compliance tests
5. Run tests with `pytest`
6. Only then mark task complete

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

## Claude Code Integration

### Specialized Agents

Use the Task tool with these agents for specific workflows:

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `optaic-compliance-reviewer` | Framework compliance + tests | After any implementation |
| `quant-domain-modeler` | Implement quant resources | Adding Dataset, Signal, Portfolio, etc. |
| `data-pipeline-engineer` | Data pipelines, ETL, PIT | Building data ingestion/processing |
| `sdk-extension-developer` | Extend Python SDK | Adding client methods |
| `guardrails-contract-designer` | Validation contracts | Adding signal bounds, constraints |
| `activity-audit-implementer` | Activity emission | Ensuring audit compliance |
| `pre-commit-reviewer` | Lint, security, tests | Before committing |
| `unit-test-generator` | Generate unit tests | After writing code |

### Framework Skills (Reference)

These skills provide detailed patterns - read them or reference when implementing:

| Skill | Content |
|-------|---------|
| `code-review` | Review checklist, anti-patterns |
| `code-test` | Test generation patterns |
| `activity-logging` | ActivityEnvelope patterns |
| `guardrails-contracts` | Validation contract design |
| `quant-resource-patterns` | Domain resource patterns |
| `data-pipeline-patterns` | PIT, Arrow, quality checks |
| `sdk-patterns` | SDK extension patterns |

### How Agents Use Skills

Agents read skill files for detailed patterns:
```
Agent (optaic-compliance-reviewer)
  ├── Reads: .claude/skills/code-review/SKILL.md
  ├── Reads: .claude/skills/code-review/references/checklist.md
  ├── Reads: .claude/skills/code-test/SKILL.md
  └── Applies patterns to review/fix/test code
```

### Blueprint Reference

The authoritative system specification is in `optaic_quant_platform_blueprint.md`. Consult it for:
- Resource taxonomy (Definitions, Instances, Runs)
- Governance rules (spaces, subspaces, promotion)
- Activity event schemas
- Pipeline semantics
