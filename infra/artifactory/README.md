# OptAIC Artifactory (Windows, Promotion Lanes)

This folder sets up a Windows-only local artifactory using three separate
pypiserver instances (staging/uat/prod). Each lane uses an isolated packages
directory and its own port.

## Layout

Default root (override with `-BaseDir`):

```
D:\optaic-artifactory\
  staging\packages\
  uat\packages\
  prod\packages\
  approvals\
  auth\
  logs\
```

## Quick Start

Prereq: Python 3.12 or lower (pypiserver currently depends on `cgi`, which was removed in 3.13).

1) Run setup (creates folders + htpasswd + installs deps):

```
.\infra\artifactory\setup_artifactory.ps1
```

2) Start the lanes (three terminals):

```
.\infra\artifactory\run_lane.ps1 -Lane staging
.\infra\artifactory\run_lane.ps1 -Lane uat
.\infra\artifactory\run_lane.ps1 -Lane prod
```

Default URLs:

- staging: `http://<host>:8081/simple/`
- uat: `http://<host>:8082/simple/`
- prod: `http://<host>:8083/simple/`

## Upload with twine

Example (staging):

```
python -m twine upload --repository-url http://<host>:8081/ ^
  -u optaic -p change-me dist/optaic-*.whl dist/optaic-*.tar.gz
```

## Promotion approval gate (optional)
Promotions can require approval files unless `-Force` is used.

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

Example promotion (gated):
```
.\scripts\devops\promote.ps1 -FromLane staging -ToLane uat -Version 0.3.7
```

Bypass gate:
```
.\scripts\devops\promote.ps1 -FromLane staging -ToLane uat -Version 0.3.7 -Force
```

## Services (optional)

To install as a Windows service (NSSM) or scheduled task fallback:

```
.\infra\artifactory\install_lane_service.ps1 -Lane staging
.\infra\artifactory\install_lane_service.ps1 -Lane uat
.\infra\artifactory\install_lane_service.ps1 -Lane prod
```

## Security Notes

- Prefer HTTPS (reverse proxy) if possible.
- If you must use HTTP, clients need `PIP_TRUSTED_HOST=<host>`.
- `--disable-fallback` is enabled, so the server never proxies to public PyPI.
