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

## Install / upgrade
```powershell
pip install optaic
pip install --upgrade optaic
```

## Testers on staging/uat
Change your `index-url` to the desired lane:
- staging: `http://<host>:8081/simple`
- uat: `http://<host>:8082/simple`

Dependencies still resolve from `https://pypi.org/simple` via `extra-index-url`.
