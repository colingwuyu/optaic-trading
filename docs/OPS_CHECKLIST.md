# OptAIC Ops Checklist (Windows)

## Daily Ops
- Verify artifactory lane health:
  - staging: `http://<host>:8081/simple/`
  - uat: `http://<host>:8082/simple/`
  - prod: `http://<host>:8083/simple/`
- Check `D:\optaic-artifactory\logs\` for errors.
- Check `DATA_DIR\state\upgrade.log` for failed upgrades.
- Confirm disk space on artifactory host and OptAIC hosts.

### Quick Diagnostics
```powershell
optaic doctor            # Full system check
```

### Runtime Monitoring
- `GET /system/runtime` — JSON health for monitoring tools
- State files:
  - `DATA_DIR\state\installed.json` — Component versions and modes
  - `DATA_DIR\state\services_state.json` — Running service status
  - `DATA_DIR\state\ports.json` — Port allocations

### Engine Health Checks (if enabled)
- Prefect (if `--with-prefect`):
  - UI: `http://localhost:4200/` (or configured port)
  - API: `http://localhost:4200/api/health`
- MLflow (if `--with-mlflow`):
  - UI: `http://localhost:5000/` (or configured port)
  - API: `http://localhost:5000/health`
- Check `DATA_DIR\state\engines_state.json` for version info


## Before Promotion
- Ensure staging smoke tests passed.
- Run UAT checklist for the candidate version.
- Verify `CHANGELOG.md` is updated.
- Confirm lane indexes list the version (use `scripts/devops/verify_index.ps1`).

## Incident Rollback Procedure
1) Identify the last known good version.
2) Roll back the OptAIC package:
   ```powershell
   pip install optaic==<X.Y.Z>
   ```
3) Roll back tools if needed:
   ```powershell
   optaic rollback --tool centrifugo --to-version <X.Y.Z>
   optaic rollback --tool redis --to-version <X.Y.Z>
   ```
4) Restart the server:
   ```powershell
   optaic server
   ```
5) Capture logs:
   - `DATA_DIR\state\upgrade.log`
   - `DATA_DIR\logs\`
   - artifactory lane logs

## Engine Migration Failure Recovery
If Prefect or MLflow fails to start after upgrade:

1) Check the migration log:
   ```powershell
   cat $env:LOCALAPPDATA\OptAIC\data\state\upgrade.log | Select-String "engine"
   ```

2) Find the backup:
   - Prefect: `DATA_DIR\engines\prefect\backups\<timestamp>\`
   - MLflow: `DATA_DIR\engines\mlflow\backups\<timestamp>\`

3) Options:
   - **Restore backup**: Copy backup DB back to original location
   - **Reset DB** (loses data):
     ```powershell
     optaic server --with-prefect --reset-prefect-db
     optaic server --with-mlflow --reset-mlflow-db
     ```
   - **Roll back package**:
     ```powershell
     pip install prefect==<previous-version>
     pip install mlflow==<previous-version>
     ```

See [ENGINES_UPGRADE_RULES.md](ENGINES_UPGRADE_RULES.md) for full details.

## Post-Incident Review
- Record timeline, root cause, and remediation steps.
- Update runbooks and checklists as needed.

