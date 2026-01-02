# Deployment Guide

This guide covers deploying OptAIC on Windows systems (desktop or server).

## Deployment Architecture

```
Windows Server
├── Python 3.11+ (system or venv)
├── OptAIC wheel installed
├── Data directory: %LOCALAPPDATA%\OptAIC\data\
│   ├── optaic.db (SQLite) or connect to PostgreSQL
│   ├── bin/centrifugo/6.1.0/
│   ├── bin/redis/8.4.0/ (optional)
│   ├── state/installed.json
│   └── prefect/, mlflow/ (optional)
└── Processes managed by optaic CLI
    ├── uvicorn (API)
    ├── worker (outbox consumer)
    ├── agent (activity-driven)
    └── centrifugo (realtime)
```

## Quick Start

### 1. Install

```powershell
# Create virtual environment (recommended)
python -m venv C:\optaic\venv
C:\optaic\venv\Scripts\activate

# Install from Artifactory
pip install optaic[server] `
    --index-url http://artifactory:8083/simple `
    --extra-index-url https://pypi.org/simple `
    --trusted-host artifactory
```

### 2. Configure

Set environment variables (or use `optaic.toml`):

```powershell
# Required
$env:MODE = "embedded"  # or "prod" for PostgreSQL

# Database (SQLite embedded or PostgreSQL)
$env:DATABASE_URL = "sqlite:///C:/optaic/data/optaic.db"
# Or: $env:DATABASE_URL = "postgresql+asyncpg://user:pass@host:5432/optaic"

# Artifactory channel
$env:OPTAIC_CHANNEL = "prod"  # staging, uat, prod
$env:OPTAIC_ARTIFACTORY_BASE_URL = "http://artifactory"

# Security (change in production!)
$env:CENTRIFUGO_API_KEY = "your-api-key"
$env:CENTRIFUGO_TOKEN_SECRET = "your-secret"
```

### 3. Start Server

```powershell
# Basic start
optaic server

# With options
optaic server --host 0.0.0.0 --port 8080 --with-redis

# Background (Windows service recommended for production)
Start-Process optaic -ArgumentList "server","--port","8080"
```

### 4. Verify

```powershell
optaic doctor

# Access WebUI
Start-Process "http://localhost:8080"
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODE` | `embedded` | `embedded` (SQLite) or `prod` (PostgreSQL) |
| `DATABASE_URL` | auto | Connection string |
| `OPTAIC_DATA_DIR` | `%LOCALAPPDATA%\OptAIC\data` | Data directory |
| `OPTAIC_CHANNEL` | `prod` | Artifactory lane |
| `OPTAIC_ARTIFACTORY_BASE_URL` | - | Artifactory URL |
| `OPTAIC_WITH_REDIS` | `false` | Enable Redis |
| `OPTAIC_REDIS_URL` | - | External Redis |
| `OPTAIC_WITH_PREFECT` | `false` | Enable Prefect |
| `OPTAIC_WITH_MLFLOW` | `false` | Enable MLflow |
| `API_HOST` | `127.0.0.1` | API bind address |
| `API_PORT` | `8080` | API port |
| `CENTRIFUGO_API_KEY` | `dev-api-key` | Centrifugo auth |
| `CENTRIFUGO_TOKEN_SECRET` | `dev-secret-change-me` | JWT secret |

### Configuration File

Create `optaic.toml` in the data directory:

```toml
[server]
host = "0.0.0.0"
port = 8080

[database]
url = "postgresql+asyncpg://user:pass@localhost:5432/optaic"

[centrifugo]
api_key = "production-key"
token_secret = "production-secret"

[engines]
prefect = "local"  # or remote URL
mlflow = "local"   # or remote URL

[package]
channel = "prod"
artifactory_base_url = "http://artifactory"
```

## Service Management

### As Windows Service (Recommended for Production)

Use NSSM or similar:

```powershell
# Install NSSM
choco install nssm

# Create service
nssm install OptAIC "C:\optaic\venv\Scripts\optaic.exe"
nssm set OptAIC AppParameters "server --host 0.0.0.0 --port 8080"
nssm set OptAIC AppDirectory "C:\optaic"
nssm set OptAIC AppEnvironmentExtra "DATABASE_URL=..." "CENTRIFUGO_API_KEY=..."

# Manage
nssm start OptAIC
nssm stop OptAIC
nssm restart OptAIC
```

### As Scheduled Task

```powershell
$action = New-ScheduledTaskAction `
    -Execute "C:\optaic\venv\Scripts\optaic.exe" `
    -Argument "server --port 8080"

$trigger = New-ScheduledTaskTrigger -AtStartup

Register-ScheduledTask -TaskName "OptAIC" `
    -Action $action `
    -Trigger $trigger `
    -User "SYSTEM" `
    -RunLevel Highest
```

## Database Options

### SQLite (Embedded Mode)

Best for single-user or small team deployments:

```powershell
$env:MODE = "embedded"
$env:DATABASE_URL = "sqlite:///C:/optaic/data/optaic.db"
optaic server
```

### PostgreSQL (Production Mode)

For multi-server or high-load deployments:

```powershell
# PostgreSQL on Windows or external server
$env:MODE = "prod"
$env:DATABASE_URL = "postgresql+asyncpg://optaic:password@db-server:5432/optaic"
optaic server
```

**Note:** PostgreSQL must be running before starting OptAIC. Migrations run automatically.

## Upgrade Procedure

### Automated (Recommended)

```powershell
# Check for updates
optaic upgrade --check-package-updates

# Dry run
optaic upgrade --dry-run

# Apply (DB migrations + binaries + self-upgrade)
optaic upgrade --apply --self --channel prod --restart

# Restart is automatic if --restart is set
```

### Manual

```powershell
# Stop service
nssm stop OptAIC

# Upgrade package
pip install --upgrade optaic[server] --index-url http://artifactory:8083/simple

# Run migrations
optaic upgrade --apply

# Start service
nssm start OptAIC
```

## Health Checks

### CLI Doctor

```powershell
optaic doctor

# Output:
# OptAIC Doctor
# ─────────────
# Version: 0.3.7
# Data directory: C:\optaic\data
# Database: postgresql+asyncpg://...@db:5432/optaic (OK)
# Schema version: h1b2c3d4e5f6 (current)
# Centrifugo: 6.1.0 (running on :8000)
# Redis: 8.4.0 (running on :6379)
# Prefect: local (running)
# MLflow: local (running)
# Channel: prod
```

### API Health Endpoint

```powershell
Invoke-RestMethod http://localhost:8080/health

# Response: { "status": "healthy", "version": "0.3.7" }
```

## Logging

Logs use structlog with JSON output:

```powershell
# Set log level
$env:OPTAIC_LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR

# Logs go to stdout by default
optaic server 2>&1 | Tee-Object -FilePath C:\optaic\logs\server.log
```

## Backup & Recovery

### Data Directory

```powershell
# Backup
Compress-Archive -Path C:\optaic\data -DestinationPath backup.zip

# Restore
Expand-Archive -Path backup.zip -DestinationPath C:\optaic\data
```

### Database Only

**SQLite:**
```powershell
Copy-Item C:\optaic\data\optaic.db C:\backups\optaic-$(Get-Date -Format "yyyyMMdd").db
```

**PostgreSQL:**
```powershell
pg_dump -h db-server -U optaic optaic > backup.sql
```

## Security Checklist

- [ ] Change `CENTRIFUGO_API_KEY` from default
- [ ] Change `CENTRIFUGO_TOKEN_SECRET` from default
- [ ] Use HTTPS with reverse proxy (nginx/IIS)
- [ ] Firewall: Only expose ports 80/443
- [ ] Use PostgreSQL for production (not SQLite)
- [ ] Regular backups
- [ ] Monitor disk space (data directory)

## Troubleshooting

### Server Won't Start

1. Check `optaic doctor` for diagnostics
2. Verify DATABASE_URL is correct
3. Check port availability: `netstat -an | findstr :8080`
4. Check logs for startup errors

### Database Migration Fails

```powershell
# Check current schema version
optaic doctor

# Retry migrations
optaic upgrade --apply

# Manual rollback if needed
optaic rollback --tool db --to-version <previous>
```

### Centrifugo Won't Start

```powershell
# Check binary exists
Test-Path $env:LOCALAPPDATA\OptAIC\data\bin\centrifugo\*

# Redownload
Remove-Item $env:LOCALAPPDATA\OptAIC\data\bin\centrifugo -Recurse
optaic server  # Auto-downloads
```
