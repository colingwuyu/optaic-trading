# Services Lifecycle Guide

How OptAIC manages sidecar services (Prefect, MLflow, Centrifugo, Redis).

---

## Quick Reference

| Path | Purpose |
|------|---------|
| `DATA_DIR/state/pids/` | PID files for running processes |
| `DATA_DIR/state/ports.json` | Reserved port allocations |
| `DATA_DIR/state/services_state.json` | Runtime service status |
| `DATA_DIR/state/installed.json` | Installed component versions |
| `DATA_DIR/logs/` | Service log files |

---

## Startup Order

When `optaic server` starts, services launch in this order:

1. **DB Migrations** — Core OptAIC schema
2. **Engine Migrations** — Prefect/MLflow DB upgrades (if local mode)
3. **Redis** — Optional, before Centrifugo if using redis engine
4. **Centrifugo** — WebSocket server
5. **Prefect Server** — Workflow orchestration
6. **Prefect Worker** — Task execution
7. **MLflow** — Experiment tracking
8. **API** — OptAIC HTTP API
9. **Worker** — Background tasks
10. **Agent** — Trading agent

**Shutdown is the reverse order.**

---

## PID Files

Each service writes a PID file on startup:

```
DATA_DIR/state/pids/
├── prefect-server.pid
├── prefect-worker.pid
├── mlflow.pid
└── centrifugo.pid
```

**On Ctrl+C:**
1. Signal handler catches SIGINT/SIGTERM
2. Services stopped in reverse order
3. Each process sent SIGTERM, waits 5s, then SIGKILL
4. PID files removed after process exit

**Stale PIDs:** `optaic doctor` auto-cleans PIDs for dead processes.

---

## Port Selection

Ports are allocated deterministically:

1. Check `ports.json` for previous allocation
2. If available, reuse it
3. If busy, scan range `[preferred, preferred+50]`
4. Fallback: OS assigns a free port
5. Save to `ports.json`

**Default ports:**
| Service | Port |
|---------|------|
| API | 8080 |
| Centrifugo | 8081 |
| Prefect | 4200 |
| MLflow | 5000 |
| Redis | 6379 |

**Collision troubleshooting:**
```powershell
netstat -ano | findstr :4200
```

---

## Local vs Remote Mode

### Prefect

**Local mode** (default):
```toml
[prefect]
enabled = true
# No api_url = starts local server
```

**Remote mode:**
```toml
[prefect]
enabled = true
api_url = "https://prefect.example.com/api"
```

### MLflow

**Local mode** (default):
```toml
[mlflow]
enabled = true
# No tracking_uri = starts local server
```

**Remote mode:**
```toml
[mlflow]
enabled = true
tracking_uri = "https://mlflow.example.com"
```

---

## State Files

### `installed.json`
What is configured (persists across restarts):
- OptAIC version, Python version
- Component versions and modes
- Port assignments
- Data paths

### `services_state.json`
What is running (overwritten each startup):
- Service status (running/stopped/error)
- PIDs, ports, URLs
- Health check timestamps

### `ports.json`
Reserved port allocations for deterministic restarts.

---

## Crash Recovery

**If a service crashes:**
1. Other services continue running
2. Health checks detect the failure
3. `optaic doctor` shows service as down with last 30 log lines

**Manual restart:**
```bash
optaic server stop
optaic server start
```

---

## Diagnostics

### `optaic doctor`
```
============================================================
OptAIC Doctor Report
============================================================
DATA_DIR: C:\Users\colin\data\optaic
✓ DATA_DIR: C:\Users\colin\data\optaic
✓ Prefect Engine: Local mode on port 4200
✗ Service: prefect-server: Not responding on port 4200
    Last log lines: ...
    → Check log file: C:\...\logs\prefect-server.log
============================================================
```

### `GET /system/runtime`
Returns JSON with service health for monitoring tools.
