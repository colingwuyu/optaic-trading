# OptAIC Windows Install & Upgrade (Channels)

## Recommended pip config
Use your internal index as the primary source for OptAIC, and public PyPI for dependencies.

Create `%APPDATA%\\pip\\pip.ini`:
```ini
[global]
index-url = http://<host>:8083/simple
extra-index-url = https://pypi.org/simple
trusted-host = <host>
```

Channel ports:
- staging: `http://<host>:8081/simple`
- uat: `http://<host>:8082/simple`
- prod: `http://<host>:8083/simple`

---

## Install Modes (Extras)

OptAIC supports different install modes depending on your use case:

### SDK-only (lightweight client)
```powershell
pip install optaic[sdk]
```
Use for applications that only need to call OptAIC APIs. No server or engine dependencies.

### Server minimal (external engines)
```powershell
pip install optaic[server]
```
Use when pointing to external Prefect/MLflow servers. Configure in `optaic.toml`:
```toml
[prefect]
enabled = true
api_url = "http://prefect-host:4200/api"

[mlflow]
enabled = true
tracking_uri = "http://mlflow-host:5000"
```

### Full local stack
```powershell
pip install optaic[all]
```
Includes server + all local engines (Prefect, MLflow, Redis client).
Then run:
```powershell
optaic server --with-prefect --with-mlflow
```

### Individual extras
```powershell
pip install optaic[prefect]   # Prefect orchestration
pip install optaic[mlflow]    # MLflow tracking
pip install optaic[redis]     # Redis client
pip install optaic[realtime]  # Centrifugo token signing
```

### Development
```powershell
pip install optaic[dev]
```

---

## Install / upgrade
```powershell
pip install optaic[all]
pip install --upgrade optaic[all]
```

## Testers on staging/uat
Change your `index-url` to the desired lane:
- staging: `http://<host>:8081/simple`
- uat: `http://<host>:8082/simple`

Dependencies still resolve from `https://pypi.org/simple` via `extra-index-url`.

