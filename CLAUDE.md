# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Unit Test Requirements Policy

### All Tasks Must Pass Unit Tests
The agent must ensure that all code implementations and resulting tasks, excluding pure documentation updates, have passing unit tests before reporting completion to the user.

- **Pre-report verification:** Always run the project's test suite as a final step.
- **Do not proceed if tests fail:** If tests fail, the agent must troubleshoot and fix the failures before considering the task complete.

### Zero Warnings Policy
All tests must not only pass, but also execute without any warnings (e.g., deprecation warnings, linting warnings, compiler warnings).

- **Warning Resolution:** If any warnings occur during the test run or compilation, the agent is responsible for resolving them as if they were errors.
- **Clean Output:** The final report to the user must confirm that the test output is entirely clean of warnings and errors.

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
