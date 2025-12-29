# pip Configuration (Windows)

Use your internal artifactory lane as the primary index and public PyPI as the extra index.

Lane URLs:
- staging: `http://<host>:8081/simple`
- uat: `http://<host>:8082/simple`
- prod: `http://<host>:8083/simple`

## Option A: pip.ini (user-level)
Location:
```
%APPDATA%\pip\pip.ini
```

Contents:
```
[global]
index-url = http://<host>:8083/simple
extra-index-url = https://pypi.org/simple
trusted-host = <host>
```

## Option B: Environment variables
```
set PIP_INDEX_URL=http://<host>:8083/simple
set PIP_EXTRA_INDEX_URL=https://pypi.org/simple
set PIP_TRUSTED_HOST=<host>
```

## OptAIC upgrade settings
OptAIC reads these optional environment variables:
```
set OPTAIC_CHANNEL=prod
set OPTAIC_ARTIFACTORY_BASE_URL=http://<host>
set OPTAIC_PACKAGE_INDEX_URL=http://<host>:8083/simple
set OPTAIC_PACKAGE_EXTRA_INDEX_URL=https://pypi.org/simple
set OPTAIC_PACKAGE_TRUSTED_HOST=<host>
set OPTAIC_PACKAGE_NAME=optaic
```

## Security notes
- Keep the internal server as `index-url` (primary).
- Use `extra-index-url` for public dependencies.
- Prefer HTTPS for the internal server. If HTTP, use `trusted-host`.
