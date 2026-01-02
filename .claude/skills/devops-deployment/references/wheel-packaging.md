# Wheel Packaging & Distribution

This document details how OptAIC is packaged as a Python wheel and distributed to users.

## Package Structure

```
optaic-0.3.7-py3-none-any.whl
├── optaic/
│   ├── __init__.py
│   ├── cli.py              # Entry point
│   ├── config.py           # Environment settings
│   ├── version.py          # Version detection
│   ├── infra/
│   │   └── versions.json   # Binary manifest
│   ├── runtime/
│   │   ├── supervisor.py   # Service orchestration
│   │   ├── migrate.py      # DB migrations
│   │   ├── upgrade_manager.py
│   │   └── ...
│   └── webui_dist/         # Embedded React UI
│       ├── index.html
│       ├── assets/
│       └── .buildinfo.json
├── apps/api/               # FastAPI application
├── apps/worker/            # Outbox consumer
├── apps/agent/             # Activity-driven agent
├── libs/core/              # Domain logic
├── libs/db/                # SQLAlchemy models + Alembic
│   ├── alembic.ini
│   └── migrations/
└── libs/sdk_py/            # Python SDK
```

## Dependency Extras

Users install the wheel with extras based on their use case:

```bash
# Researcher using SDK only (lightweight)
pip install optaic[sdk]

# Server operator (full stack)
pip install optaic[server]

# Full install with all optional engines
pip install optaic[all]

# Development
pip install -e .[dev]
```

### Extra Definitions

| Extra | Dependencies | Use Case |
|-------|--------------|----------|
| `sdk` / `client` | pydantic, httpx | SDK users, notebooks |
| `server` | FastAPI, SQLAlchemy, aiosqlite, asyncpg, alembic, pycasbin | Running server |
| `realtime` | PyJWT, websockets | Centrifugo integration |
| `engines` | prefect, mlflow | Orchestration & tracking |
| `redis` | redis | Redis caching |
| `storage` | boto3 | S3 storage |
| `all` / `full` | All above | Full local install |
| `dev` | pytest, ruff, mypy, pre-commit | Development |

### pyproject.toml Excerpt

```toml
[project]
name = "optaic"
version = "0.3.7"
requires-python = ">=3.11"

dependencies = [
    "pydantic-settings>=2.3",
    "platformdirs>=4.2",
    "structlog>=24.2",
    "typer>=0.12",
    "packaging>=24.0",
]

[project.optional-dependencies]
sdk = [
    "pydantic>=2.0",
    "httpx>=0.25",
]
server = [
    "optaic[sdk]",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0.30",
    "aiosqlite>=0.20",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pycasbin>=1.27",
    # ...
]
all = [
    "optaic[server,engines,redis,storage,realtime]",
]
dev = [
    "optaic[all]",
    "pytest>=8.2",
    "pytest-asyncio>=1.3",
    "ruff>=0.4",
    "mypy>=1.10",
    "pre-commit>=3.7",
]

[project.scripts]
optaic = "optaic.cli:main"

[tool.setuptools.package-data]
"*" = ["*.json", "*.ini", "*.html", "*.css", "*.js", "*.map", "*.ico", "*.svg", "*.png"]
"optaic" = ["webui_dist/**"]
"libs.db" = ["alembic.ini", "migrations/**"]
```

## Build Process

### 1. Development Build

```bash
# Build wheel only
uv build

# Output:
# dist/optaic-0.3.7-py3-none-any.whl
# dist/optaic-0.3.7.tar.gz
```

### 2. Full Release Build

```bash
# Run quality checks + build
python scripts/release_build.py

# Steps:
# 1. ruff check .
# 2. pytest
# 3. uv build
```

### 3. WebUI Build

The React UI must be built before packaging:

```bash
python scripts/build_webui.py

# Steps:
# 1. cd apps/web && npm ci
# 2. npm run build
# 3. Copy dist/ to optaic/webui_dist/
# 4. Write .buildinfo.json with git commit + timestamp
```

### 4. Publish to Artifactory

```bash
# Set credentials
export OPTAIC_PYPI_REPO_URL=http://artifactory:8081/
export OPTAIC_PYPI_USERNAME=admin
export OPTAIC_PYPI_PASSWORD=secret

# Publish
python scripts/release_publish.py

# Uses twine upload internally
```

## Version Management

### Version Source

Version is defined in `pyproject.toml`:

```toml
[project]
version = "0.3.7"
```

### Runtime Version Detection

`optaic/version.py` reads from installed package metadata:

```python
def get_version() -> str:
    try:
        from importlib.metadata import version
        return version("optaic")
    except Exception:
        return "0.0.0"
```

### CLI Version Command

```bash
$ optaic version
optaic 0.3.7
```

## Data Files & Resources

### Embedded Files

The wheel includes non-Python files via `package-data`:

| Resource | Path | Purpose |
|----------|------|---------|
| WebUI | `optaic/webui_dist/` | React SPA |
| Binary manifest | `optaic/infra/versions.json` | Centrifugo/Redis versions |
| Alembic config | `libs/db/alembic.ini` | Migration settings |
| Migrations | `libs/db/migrations/` | Schema versions |

### Accessing Resources at Runtime

```python
from importlib import resources

# Access versions.json
with resources.open_text("optaic.infra", "versions.json") as f:
    manifest = json.load(f)

# Access migration files (for wheel installs)
from optaic.runtime.migrate import migration_paths
alembic_ini, migrations_dir = migration_paths()
```

## Workspace Structure

The monorepo uses uv workspaces:

```toml
# pyproject.toml
[tool.uv]
workspace = { members = [
    "apps/api",
    "apps/agent",
    "apps/worker",
    "libs/core",
    "libs/db",
    "libs/sdk_py",
] }
```

Each workspace member has its own `pyproject.toml` but shares the virtual environment.

## Installation Scenarios

### 1. Development (Editable)

```bash
uv venv
uv pip install -e .[dev]

# Or using uv sync
uv sync --group dev
```

### 2. Server Deployment

```bash
pip install optaic[server] \
    --index-url http://artifactory:8083/simple \
    --extra-index-url https://pypi.org/simple

optaic server --host 0.0.0.0 --port 8080
```

### 3. SDK Only (Researchers)

```bash
pip install optaic[sdk] \
    --index-url http://artifactory:8083/simple

# In Python/notebook
from libs.sdk_py import AsyncPlatformClient

client = AsyncPlatformClient(base_url="http://server:8080")
```

### 4. Upgrade Existing Installation

```bash
# Via CLI (preferred)
optaic upgrade --apply --self --channel prod

# Or manually
pip install --upgrade optaic[server] --index-url ...
optaic upgrade --apply  # Run migrations
```

## Verification

After installation, verify with:

```bash
# Check version
optaic version

# Diagnostics
optaic doctor

# Output:
# OptAIC Doctor
# ─────────────
# Version: 0.3.7
# Data directory: C:\Users\...\AppData\Local\OptAIC\data
# Database: sqlite:///C:\...\optaic.db (OK)
# Schema version: h1b2c3d4e5f6 (current)
# Centrifugo: 6.1.0 (running)
# Channel: prod
```
