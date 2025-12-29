# Engine DB Upgrade Rules (Prefect/MLflow)

This document describes how OptAIC manages Prefect and MLflow database migrations, backups, and recovery procedures.

## DATA_DIR Locations

Engine data lives under `DATA_DIR/engines/`:

```
DATA_DIR/
  engines/
    prefect/
      home/                     # PREFECT_HOME directory
        prefect.db              # Prefect SQLite database
      backups/
        <timestamp>/
          prefect.db            # Pre-migration backup
    mlflow/
      backend/
        mlflow.db               # MLflow SQLite database
      artifacts/                # Default artifact store
      backups/
        <timestamp>/
          mlflow.db             # Pre-migration backup
  state/
    engines_state.json          # Tracks engine versions
    upgrade.log                 # Append-only audit log
    lockfile                    # Exclusive lock for upgrades
```

Default `DATA_DIR`: `%LOCALAPPDATA%\OptAIC\data` (Windows)

Override: `OPTAIC_DATA_DIR` environment variable or `data_dir` in `optaic.toml`

---

## When Migrations Run

Migrations run automatically:

1. **On `optaic server` start** — before engines start, if version changed
2. **On `optaic upgrade --apply`** — as part of the upgrade workflow

The system compares the installed package version (`prefect.__version__`, `mlflow.__version__`) against the recorded version in `engines_state.json`.

---

## Upgrade Behavior

When the installed package version is **greater than** the recorded version:

1. **Backup** — Engine DB copied to `DATA_DIR/engines/<engine>/backups/<timestamp>/`
2. **Migrate** — Schema upgrade command runs:
   - Prefect: `prefect server database upgrade -y`
   - MLflow: `mlflow db upgrade <backend_store_uri>`
3. **Update state** — `engines_state.json` updated with new version and timestamps
4. **Log** — Entry appended to `upgrade.log`

If migration **fails**:
- Engine does NOT start
- Error logged to `upgrade.log`
- Error message includes backup path for recovery

---

## Downgrade Policy

> **Downgrades are blocked by default.**

If the installed package version is **less than** the recorded version, the engine will refuse to start because database schema downgrades are not safe.

### Override Flags (Use with Caution)

| Flag | Effect |
|------|--------|
| `--allow-engine-downgrade` | Allows running with older version (DANGEROUS — schema mismatch possible) |
| `--reset-prefect-db` | Creates backup, then deletes Prefect DB (fresh start) |
| `--reset-mlflow-db` | Creates backup, then deletes MLflow DB (fresh start) |

Example:
```powershell
optaic server --with-prefect --reset-prefect-db
```

---

## Recovery Playbooks

### Migration Failure

1. **Check the error**:
   ```powershell
   cat $env:LOCALAPPDATA\OptAIC\data\state\upgrade.log
   ```

2. **Find the backup**:
   - Prefect: `DATA_DIR\engines\prefect\backups\<timestamp>\prefect.db`
   - MLflow: `DATA_DIR\engines\mlflow\backups\<timestamp>\mlflow.db`

3. **Restore from backup**:
   ```powershell
   # Stop the server first
   # Copy backup to original location
   copy "DATA_DIR\engines\prefect\backups\<timestamp>\prefect.db" "DATA_DIR\engines\prefect\home\prefect.db"
   ```

4. **Rollback package** (if restore doesn't work):
   ```powershell
   pip install prefect==<previous-version>
   pip install mlflow==<previous-version>
   ```

### Accidental Downgrade

If you installed an older OptAIC version and engines won't start:

1. **Option A** — Upgrade back to the version you had:
   ```powershell
   pip install optaic==<recorded-version>
   ```

2. **Option B** — Reset the engine DB (loses data):
   ```powershell
   optaic server --with-prefect --reset-prefect-db
   ```

### Corrupted State File

If `engines_state.json` is corrupted:

1. Delete the file (engines will treat it as fresh install):
   ```powershell
   del $env:LOCALAPPDATA\OptAIC\data\state\engines_state.json
   ```

2. Restart the server (migrations will run as if first install)

---

## Remote Mode (No Local Migrations)

When using remote engines, migrations do NOT run locally:

```toml
[prefect]
enabled = true
api_url = "http://remote-prefect:4200/api"  # → mode = "remote"

[mlflow]
enabled = true
tracking_uri = "http://remote-mlflow:5000"  # → mode = "remote"
```

In remote mode:
- No local server subprocess is started
- No local DB exists to migrate
- The remote server is responsible for its own migrations

---

## Checking Engine State

View current engine state:
```powershell
cat $env:LOCALAPPDATA\OptAIC\data\state\engines_state.json
```

Example output:
```json
{
  "schema_version": 1,
  "engines": {
    "prefect": {
      "mode": "local",
      "package_version": "3.1.0",
      "home_dir": "C:/Users/.../engines/prefect/home",
      "last_migrated_at": "2025-12-28T20:00:00Z",
      "last_backup_at": "2025-12-28T20:00:00Z"
    },
    "mlflow": {
      "mode": "local",
      "package_version": "2.15.0",
      "backend_store_uri": "sqlite:///...",
      "last_migrated_at": "2025-12-28T20:00:00Z"
    }
  }
}
```

---

## Best Practices

1. **Always backup before upgrades** — Migrations auto-backup, but manual backups are recommended for critical deployments
2. **Test upgrades in staging** — Use the staging lane before promoting to production
3. **Don't skip major versions** — Upgrade incrementally if possible
4. **Check upgrade.log after issues** — It contains detailed migration outcomes
5. **Use remote mode for shared infrastructure** — Avoids local migration complexity
