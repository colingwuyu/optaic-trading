# OptAIC (Resource Activity Platform)

A platform for resource management and activity tracking with a bundled web UI
and a Windows-friendly embedded runtime.

## Documentation Entry Point

### Start Here
- [Windows developer setup](docs/DEV_SETUP_WINDOWS.md)
- [DevOps runbook (end-to-end)](docs/DEVOPS_RUNBOOK.md)
- [Ops checklist](docs/OPS_CHECKLIST.md)
- [User install & upgrade (Windows)](docs/USER_INSTALL_WINDOWS.md)

### DevOps & Release
- [Release flow + promotion lanes](docs/devops_release.md)
- [Services lifecycle (startup/shutdown)](docs/SERVICES_LIFECYCLE.md)
- [Engine DB upgrade rules](docs/ENGINES_UPGRADE_RULES.md)
- [pip config (internal lanes)](docs/pip_config_windows.md)
- [Artifactory lanes (Windows)](infra/artifactory/README.md)
- [DevOps scripts usage](scripts/devops/README.md)



## What This System Does
- Provides a unified resource/activity platform with chat, realtime updates, and audit trails.
- Ships a single `optaic` CLI that boots API + worker + agent + Centrifugo and serves the UI.
- Supports Windows-first, Docker-optional deployment with automatic DB migrations.
- Enables lane-based promotion (staging → UAT → prod) via internal artifactory.

## Quant Domain Features (Phase 2)
- **Data Pipelines**: Flexible ETL pipelines (FRED, Bloomberg, Expression) integrated with governance.
- **Dataset Management**: Versioned datasets with PIT (Point-in-Time) access and lineage tracking.
- **Signal Engine**: Promote datasets to signals with validation contracts and audit trails.
- **Operator Library**: Built-in library of time-series (REF, DELTA), statistical (MEAN, STD), and math operators.
- **Guardrails**: Policy enforcement for data contracts (schema, bounds, freshness).
- **Extensible SDK**: Python SDK extensions for datasets, signals, and pipelines.

## Phase 3: Research & Experimentation
- **Expression Experiments**: Sandbox for testing signals and strategies using the expression engine (MEAN, SUM, etc.).
- **Macro Definitions**: Save successful experiments as reusable `OpMacroDef` resources for use in production pipelines.
- **Vintage Data Support**: Full Point-in-Time (PIT) correctness with `EconomicsAccessor` for revision-aware macroeconomic data.

## Tech Stack
- Python 3.11+
- FastAPI (ASGI)
- React web UI (served by the API)
- SQLAlchemy + Alembic migrations
- SQLite (embedded) and Postgres (prod)
- Centrifugo (realtime, memory or Redis engine)
- Redis (optional)
- MinIO (attachments, Docker dev)

## Repository Structure
- `optaic`: distributable package + CLI + runtime supervisor
- `apps/api`: FastAPI application
- `apps/worker`: Outbox consumer + notifications stub
- `apps/agent`: LLM agent runner (activity-driven)
- `apps/web`: React UI
- `libs/core`: Domain models, RBAC, activity envelope
- `libs/db`: SQLAlchemy base, session, Alembic env
- `libs/sdk_py`: Thin Python SDK client
- `infra`: Infrastructure config (artifactory lanes, Docker Compose)

## Quickstart (Windows, Embedded)
1. Install dependencies:
   ```powershell
   uv venv
   uv pip install -e . --group dev
   ```

2. (Optional) seed demo data:
   ```powershell
   optaic init-demo
   ```

3. Start the stack:
   ```powershell
   optaic server
   ```
   With local Prefect + MLflow engines:
   ```powershell
   optaic server --with-prefect --with-mlflow
   ```

4. Open the UI:
   ```powershell
   http://localhost:8080/
   ```

See [Windows developer setup](docs/DEV_SETUP_WINDOWS.md) for full details.

## Quickstart (Docker, Optional)
1. Sync dependencies:
   ```bash
   uv sync
   ```

2. Start the infrastructure:
   ```bash
   docker compose -f infra/docker-compose.yml up --build
   ```

3. Check API health:
   ```bash
   curl http://localhost:8000/healthz
   ```

4. Check Centrifugo health:
   ```bash
   curl http://localhost:8001/health
   ```

5. MinIO console (optional):
   ```bash
   http://localhost:9001
   ```

## Architecture Flow (Embedded)
1. `optaic server` resolves `DATA_DIR`, runs migrations, and ensures Centrifugo binaries.
2. Supervisor starts Centrifugo, API, worker, and agent.
3. API serves the React UI at `/` and issues realtime tokens for Centrifugo.
4. Worker publishes realtime messages to Centrifugo; agent processes activity-driven tasks.

## Realtime (Centrifugo)
- Embedded mode writes config under `DATA_DIR/centrifugo/config.json`.
- Docker mode uses `infra/centrifugo/config.json`.
- Worker publishes via HTTP API using `CENTRIFUGO_URL` + `CENTRIFUGO_API_KEY`.
- API issues connection/subscription JWTs using `CENTRIFUGO_HMAC_SECRET`.

### Realtime Tokens
Use `POST /realtime/token` with dev headers to obtain a Centrifugo connection token and per-channel subscription tokens.

Example:
```bash
curl -X POST http://localhost:8000/realtime/token \
  -H "X-Principal-Id: <principal-id>" \
  -H "X-Tenant-Id: <tenant-id>" \
  -H "Content-Type: application/json" \
  -d '{
    "channels": [
      "t:<tenant-id>:u:<principal-id>",
      "t:<tenant-id>:r:<resource-id>",
      "t:<tenant-id>:c:<channel-id>"
    ]
  }'
```

The response includes:
- `connection_token`: pass as `token` when opening a Centrifugo connection.
- `subscriptions`: map of channel -> subscription token for client-side subscribe.
If any requested channel is unauthorized, the API returns 403 with `denied_channels` details.

## Developer Guide
- Setup and VSCode debugging: [docs/DEV_SETUP_WINDOWS.md](docs/DEV_SETUP_WINDOWS.md)
- DevOps workflow and promotion lanes: [docs/DEVOPS_RUNBOOK.md](docs/DEVOPS_RUNBOOK.md)
- Release flow: [docs/devops_release.md](docs/devops_release.md)

## Operations & Deployment
- User install/upgrade and channels: [docs/USER_INSTALL_WINDOWS.md](docs/USER_INSTALL_WINDOWS.md)
- Ops checklist: [docs/OPS_CHECKLIST.md](docs/OPS_CHECKLIST.md)
- Artifactory lanes: [infra/artifactory/README.md](infra/artifactory/README.md)

## Development Commands
- Run tests: `pytest`
- Format code: `ruff format .`
- Lint code: `ruff check .`
- Type check: `mypy .`
