# OptAIC DevOps Release Flow (Artifactory Lanes)

## Versioning
- Follow SemVer: MAJOR.MINOR.PATCH.
- Update `pyproject.toml` `[project].version` before building.
- Update `CHANGELOG.md` if you publish release notes.

## Developer release steps
1) Build artifacts:
```
.\scripts\devops\build.ps1
```

2) Publish to staging:
```
$env:OPTAIC_ARTI_USER="optaic"
$env:OPTAIC_ARTI_PASS="change-me"
.\scripts\devops\publish.ps1 -Lane staging -RepoBaseUrl http://<host>:8081
```

3) Verify the staging index:
```
.\scripts\devops\verify_index.ps1 -RepoBaseUrl http://<host>:8081
```

4) Promote to UAT / PROD:
```
.\scripts\devops\promote.ps1 -FromLane staging -ToLane uat -Version <X.Y.Z>
.\scripts\devops\promote.ps1 -FromLane uat -ToLane prod -Version <X.Y.Z>
```

## Legacy single-lane flow (optional)
If you still run a single pypiserver instance:
```
PowerShell -ExecutionPolicy Bypass -File .\scripts\release.ps1
```

## Notes
- Uploads go to the internal pypiserver only (no public PyPI).
- The index must serve the `/simple/` API (PEP 503).
