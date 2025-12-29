# DevOps Scripts

Scripts for building, publishing, verifying, and promoting OptAIC packages.

Requirements:
- Python available on PATH (`python` or `py`).
- `ruff`, `pytest`, `build`, and `twine` installed in your Python environment.
- For publish/verify, set env vars:
  - OPTAIC_ARTI_USER
  - OPTAIC_ARTI_PASS

Examples:

Build (lint + tests + artifacts):
```powershell
.\build.ps1
```

Publish to staging:
```powershell
.\publish.ps1 -Lane staging -RepoBaseUrl http://host:8081
```

Build + publish (one line):
```powershell
.\build.ps1; .\publish.ps1 -Lane staging -RepoBaseUrl http://host:8081
```

Verify index versions:
```powershell
.\verify_index.ps1 -RepoBaseUrl http://host:8081
```

Promote to UAT or prod:
```powershell
.\promote.ps1 -FromLane staging -ToLane uat -Version 0.3.7
.\promote.ps1 -FromLane uat -ToLane prod -Version 0.3.7
```

Approval gate (optional):
- Requires `D:\optaic-artifactory\approvals\<version>\uat_approved.json` or
  `D:\optaic-artifactory\approvals\<version>\prod_approved.json`.
- Use `-Force` to bypass the gate.
