# OptAIC Windows Developer Setup

## Prerequisites
- Windows 10/11
- Python 3.11+
- Git
- VS Code with the Python and Ruff extensions
- Optional: Node.js 20+ (only needed for the web dev server)

## Create a virtual env and install deps

### Using uv (recommended)
1) `uv venv`
2) `uv pip install -e . --group dev`

### Using venv + pip
1) `python -m venv .venv`
2) `.\.venv\Scripts\Activate.ps1`
3) `python -m pip install -e .`
4) `python -m pip install ruff pytest build twine mypy pre-commit`

## Local env defaults
The repo ships `.vscode/.env` for local dev defaults (SQLite in `.tmp/` and API port 8081).
Adjust the values if you want a different data directory or port.

## Run the API locally
```powershell
python -m uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8081
```

## Debug in VS Code
1) Select the interpreter: `.venv\Scripts\python.exe`.
2) Use the launch configs:
   - API: debug
   - Worker: debug
   - Agent: debug
   - OptAIC server: debug (runs the supervisor, Redis disabled by default)

If you run API/worker/agent directly, initialize the SQLite schema once:
```powershell
optaic upgrade --apply
```

## VS Code Tasks
Tasks are available under Terminal > Run Task:
- dev: lint
- dev: test
- dev: build
- dev: publish staging (requires OPTAIC_ARTI_USER/OPTAIC_ARTI_PASS)
- dev: promote staging->uat
- dev: promote uat->prod

## Web UI dev (optional)
```powershell
cd apps/web
npm install
npm run dev
```
