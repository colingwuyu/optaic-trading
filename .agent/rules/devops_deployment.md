---
trigger: model_decision
description: Agent trigger: Load this file when implementing deployment, packaging, CI/CD, Artifactory lanes, or testing infrastructure. Critical for understanding OptAIC's native Windows deployment model (no Docker).
---

# DevOps & Deployment Rules

OptAIC is a **native Windows application** distributed as a Python wheel. There is NO Docker in production.

## 1. Deployment Model

| Aspect | Implementation |
|--------|---------------|
| **Packaging** | Single Python wheel with extras ('pip install optaic[server]') |
| **Distribution** | Local Artifactory with lanes: staging -> uat -> prod |
| **Deployment** | 'pip install' + 'optaic server' on Windows Server |
| **Testing** | SQLite fixtures, no containers required |
| **Database** | SQLite (embedded) or PostgreSQL (external) |
| **Binaries** | Centrifugo/Redis auto-downloaded by CLI |

## 2. Anti-Patterns (DO NOT DO)

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| Docker Compose for deployment | Production is native Windows |
| Dockerfile for testing | Use local wheel install instead |
| PostgreSQL container tests | Use SQLite for embedded tests |
| Rebuilding Artifactory scripts | Already complete in 'infra/artifactory/' |
| External service dependencies | Self-contained binaries managed by CLI |
| Manual database migrations | Auto-run on 'optaic server' startup |
| Backend-specific overrides in models | Models must be backend-agnostic (Postgres & SQLite) |
| Strict Foreign Keys in Audit Logs | Audit logs must persist even if resource is missing |

## 3. Correct Patterns

### Wheel Extras
'pyproject.toml' defines modular extras for different use cases.

### Package & Dependency Management (uv)
We use 'uv' for all dependency management.
- **Install/Sync**: 'uv sync' (updates '.venv' based on 'uv.lock')
- **Add Dependency**: 'uv add <package>' (updates 'pyproject.toml' and lockfile)
- **Add Dev Dependency**: 'uv add --dev <package>'
- **Run Scripts**: 'uv run <script>' (runs in '.venv' context)

### Build & Publish
- 'uv build' - Creates dist/optaic-*.whl
- 'python scripts/release_build.py' - Full release build
- 'python scripts/release_publish.py' - Publish to Artifactory

### Artifactory Lanes
- staging (8081), uat (8082), prod (8083)
- '.\scripts\devops\promote.ps1 -Version X.Y.Z -FromLane staging -ToLane uat'

### Testing (SQLite Fixtures)
Use 'uv run pytest' for all test execution.
- **Command**: 'uv run pytest libs/db/tests/ -vv'
- **Isolation**: Each test gets a fresh session transaction or file.
- **Configuration**: 'NullPool', 'WAL' mode, 'foreign_keys=OFF'.

### Local Debugging (VS Code)
Use 'debugpy' launch configurations in '.vscode/launch.json'.
- Select the '.venv' python interpreter in VS Code.
- Use **"API: debug"** to debug the running server.
- Use **"Pytest: Current File"** to debug specific tests.

## 4. Key File Locations

| Purpose | Path |
|---------|------|
| Package config | 'pyproject.toml' |
| Launch Config | '.vscode/launch.json' |
| Artifactory setup | 'infra/artifactory/setup_artifactory.ps1' |
| Promotion gates | 'scripts/devops/promote.ps1' |
| Binary manifest | 'optaic/infra/versions.json' |
| Test fixtures | 'libs/db/tests/conftest.py' |

## 5. References

See '.claude/skills/devops-deployment/' for complete patterns:
- 'SKILL.md' - Full deployment architecture
- 'references/' - Additional examples and patterns
