# OptAIC DevOps Runbook (Windows)

## 1) Overview
- Components: `optaic` Python package, persistent data directory, DB migrations, Centrifugo, optional Redis, optional Prefect + MLflow engines, local artifactory lanes (staging/uat/prod).
- Data directory (default): `%LOCALAPPDATA%\\OptAIC\\data\\` (override with `OPTAIC_DATA_DIR`).
- DB migrations run automatically on startup (`optaic server` and `optaic upgrade --apply`).
- Centrifugo is auto-managed in embedded mode; Redis is optional and off by default.
- Prefect + MLflow run localhost-only by default; configure remote URLs in `optaic.toml`.
- Windows-only assumptions in this runbook (artifactory scripts and embedded binaries).

## 2) Developer Workflow (End-to-End)

### Dev setup (VSCode debug)
- Follow `docs/DEV_SETUP_WINDOWS.md`.
- Use the launch configs in `.vscode/launch.json`.

### Local run (embedded mode)
```powershell
optaic server
```
Run with Prefect + MLflow engines:
```powershell
optaic server --with-prefect --with-mlflow
```
Optional demo data:
```powershell
optaic init-demo
```

### Engine configuration (optaic.toml)
Place `optaic.toml` next to where you launch the CLI (or under `DATA_DIR\\optaic.toml`).

Example (local services, data persisted under `DATA_DIR`):
```toml
data_dir = "%LOCALAPPDATA%\\OptAIC\\data"

[prefect]
enabled = true
bind_host = "127.0.0.1"
port = 4200
api_url = ""
home_dir = "<DATA_DIR>/prefect"
work_pool = "optaic-process"
worker_limit = 4

[mlflow]
enabled = true
bind_host = "127.0.0.1"
port = 5000
tracking_uri = ""
backend_store_uri = "sqlite:///<DATA_DIR>/mlflow/backend/mlflow.db"
artifacts_mode = "direct"
default_artifact_root = "<DATA_DIR>/mlflow/artifacts"
```

Example (remote engines):
```toml
[prefect]
enabled = true
api_url = "http://prefect-host:4200/api"

[mlflow]
enabled = true
tracking_uri = "http://mlflow-host:5000"
```

Persistence:
- Prefect state lives in `DATA_DIR\engines\prefect\home\`.
- MLflow backend DB + artifacts live under `DATA_DIR\engines\mlflow\`.
- State files: See [SERVICES_LIFECYCLE.md](SERVICES_LIFECYCLE.md) for:
  - `DATA_DIR\state\installed.json` — Component versions
  - `DATA_DIR\state\services_state.json` — Runtime status
  - `DATA_DIR\state\ports.json` — Port allocations
  - `DATA_DIR\state\pids\` — PID files
  - `DATA_DIR\logs\` — Service logs

Security note:
- Prefect + MLflow bind to `127.0.0.1` by default. Set `bind_host` only if you intend to expose them.


### Feature development
- Implement changes.
- Update version in `pyproject.toml`.
- Update `CHANGELOG.md` (if used for release notes).

### Tests and lint
```powershell
python -m ruff check .
python -m pytest
```

### Build wheel + sdist
```powershell
.\scripts\devops\build.ps1
```

### Publish to staging lane
```powershell
$env:OPTAIC_ARTI_USER="optaic"
$env:OPTAIC_ARTI_PASS="change-me"
.\scripts\devops\publish.ps1 -Lane staging -RepoBaseUrl http://<host>:8081
```

### Staging smoke test checklist
- UI loads at `http://localhost:8080/`
- `/healthz` returns OK
- System -> Updates shows runtime info and can check for updates
- Chat realtime messages arrive
- Activity feed updates
- Agent cycles without errors
- Merge/Promotion flows open and render

### Promote staging -> UAT
```powershell
.\scripts\devops\promote.ps1 -FromLane staging -ToLane uat -Version <X.Y.Z>
```

### Promotion approval gate (optional)
Promotions to UAT/PROD require an approval file unless `-Force` is used.

Approval file paths:
- UAT: `D:\optaic-artifactory\approvals\<version>\uat_approved.json`
- PROD: `D:\optaic-artifactory\approvals\<version>\prod_approved.json`

Schema (example):
```json
{
  "version": "0.3.7",
  "from_lane": "staging",
  "to_lane": "uat",
  "approved_by": "alice",
  "approved_at": "2025-01-15T12:34:56Z",
  "ticket_id": "CHANGE-1234",
  "notes": "UAT approval"
}
```

To bypass the gate:
```powershell
.\scripts\devops\promote.ps1 -FromLane staging -ToLane uat -Version <X.Y.Z> -Force
```

### UAT checklist (multi-user)
- Create two users; verify RBAC enforcement
- Approvals flow works (RBAC required)
- Chat + activity feeds scoped correctly
- Upgrade plan and upgrade start work

### Promote UAT -> PROD
```powershell
.\scripts\devops\promote.ps1 -FromLane uat -ToLane prod -Version <X.Y.Z>
```

### Tagging / release notes
- Update `CHANGELOG.md` with notable changes.
- Tag release in Git (optional):
```powershell
git tag v<X.Y.Z>
```

## 3) Artifactory Operations (pypiserver lanes)

### Setup (once)
```powershell
.\infra\artifactory\setup_artifactory.ps1
```
Notes:
- Requires Python 3.12 or lower for pypiserver.
- Default root: `D:\optaic-artifactory\`

### Start / stop lanes
```powershell
.\infra\artifactory\run_lane.ps1 -Lane staging
.\infra\artifactory\run_lane.ps1 -Lane uat
.\infra\artifactory\run_lane.ps1 -Lane prod
```
Default URLs:
- staging: `http://<host>:8081/simple/`
- uat: `http://<host>:8082/simple/`
- prod: `http://<host>:8083/simple/`

Optional services:
```powershell
.\infra\artifactory\install_lane_service.ps1 -Lane staging
.\infra\artifactory\install_lane_service.ps1 -Lane uat
.\infra\artifactory\install_lane_service.ps1 -Lane prod
```

### Auth management
- HTpasswd is stored under `D:\optaic-artifactory\auth\`.
- Update credentials in htpasswd and re-run lane processes if needed.

### Folder layout
```
D:\optaic-artifactory\
  staging\packages\
  uat\packages\
  prod\packages\
  approvals\
  auth\
  logs\
```

### Backups
- Backup `packages\` and `logs\` regularly.
- Keep promotion log (`logs\promotion.log`).

## 4) User Deployment

### pip install from prod lane
Create `%APPDATA%\\pip\\pip.ini`:
```ini
[global]
index-url = http://<host>:8083/simple
extra-index-url = https://pypi.org/simple
trusted-host = <host>
```

Install / upgrade:
```powershell
pip install optaic
pip install --upgrade optaic
```

### First run
```powershell
optaic init-demo
optaic server
```

### Upgrade options
- CLI:
```powershell
optaic upgrade --check
optaic upgrade --apply --restart --self
```
- GUI: System -> Updates -> Upgrade now

### Rollback options
- Tool rollback:
```powershell
optaic rollback --tool centrifugo --to-version <X.Y.Z>
optaic rollback --tool redis --to-version <X.Y.Z>
```
- Package rollback:
```powershell
pip install optaic==<X.Y.Z>
```

## 5) Data & DB Upgrade Safety
- `DATA_DIR` persists across upgrades and stores DB, logs, and binaries.
- Migrations run automatically on startup and during `optaic upgrade --apply`.
- Backup/restore: stop server, copy `DATA_DIR` to a safe location, restore by copying back.

### Engine DB Migrations (Prefect/MLflow)
When OptAIC package upgrades Prefect or MLflow dependency versions:
1. **Backup** created: `DATA_DIR\engines\<engine>\backups\<timestamp>\`
2. **Migration** runs automatically (schema upgrade)
3. **State** updated in `DATA_DIR\state\engines_state.json`

Downgrade behavior:
- **Blocked by default** — prevents schema mismatch issues
- Override: `--allow-engine-downgrade` (dangerous) or `--reset-<engine>-db` (destructive)

See [ENGINES_UPGRADE_RULES.md](ENGINES_UPGRADE_RULES.md) for full details.

### Troubleshooting Migrations
  - Run `optaic doctor`.
  - Check `DATA_DIR\\state\\upgrade.log`.
  - For SQLite: ensure no other processes lock the DB.
  - For prod DB: confirm `DATABASE_URL` is reachable.

## 6) Observability & Troubleshooting
- Logs:
  - `DATA_DIR\\logs\\` (runtime logs if enabled)
  - `DATA_DIR\\state\\upgrade.log` (upgrade audit)
  - Artifactory logs in `D:\\optaic-artifactory\\logs\\`
- Diagnostics:
```powershell
optaic doctor
```
- Common issues:
  - Port conflicts: use `--port` or stop other processes.
  - Permissions: ensure data dir is writable.
  - Trusted host: set `PIP_TRUSTED_HOST` when using HTTP index.
  - Proxy: set `HTTPS_PROXY` / `HTTP_PROXY` if needed.
  - Centrifugo download: set `OPTAIC_CENTRIFUGO_PATH` to a local binary if blocked.

## Channel Selection
- Default channel: `prod`
- Override by env:
  - `OPTAIC_CHANNEL=staging|uat|prod`
  - `OPTAIC_ARTIFACTORY_BASE_URL=http://<host>`
- Override by explicit URL:
  - `OPTAIC_PACKAGE_INDEX_URL=http://<host>:8083/simple`
- GUI: System -> Updates -> Channel dropdown (admin only).
