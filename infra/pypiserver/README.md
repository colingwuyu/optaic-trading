# OptAIC Internal PyPI Server (Windows)

This directory documents a simple Windows-only internal package index using
`pypiserver` and a local wheel folder. It is intended to host OptAIC wheels
only, while clients resolve dependencies from public PyPI via `extra-index-url`.

## Prerequisites
- Windows host with Python 3.11+
- Access to create `D:\optaic-pypi\` (default paths in scripts)
- Optional: HTTPS reverse proxy in front of the server

## Directory layout
```
D:\optaic-pypi\
  packages\   # wheel + sdist files
  auth\       # htpasswd.txt
  logs\       # server logs + pid
```

## Setup
1) Run the setup script:
```
PowerShell -ExecutionPolicy Bypass -File .\infra\pypiserver\setup_server.ps1
```

2) Start the server:
```
PowerShell -ExecutionPolicy Bypass -File .\infra\pypiserver\run_pypiserver.ps1
```

3) Stop the server:
```
PowerShell -ExecutionPolicy Bypass -File .\infra\pypiserver\stop_pypiserver.ps1
```

## Notes
- The server uses `--disable-fallback` so it does NOT proxy to public PyPI.
- Clients must use `index-url` for the internal server and `extra-index-url`
  for public PyPI dependencies.
- If you use HTTP, set `pip` `trusted-host` for the pypiserver host.
