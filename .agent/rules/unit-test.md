---
trigger: always_on
---

# Definition of Done & Quality Policy

## 1. Unit Tests (Strict)
The agent must ensure that all code implementations and resulting tasks, excluding pure documentation updates, have passing unit tests before reporting completion to the user.

- **Pre-report verification:** Always run 'uv run pytest'.
- **Zero Warnings:** Tests must execute without warnings (deprecation, linting, etc).
- **Environment:** Use SQLite (in-memory/tempfile) with 'poolclass=NullPool'.
- **Configuration:** 'conftest.py' must use session-scoped engine fixtures and function-scoped rollbacks.
- **Fail Check:** Do not proceed if tests fail. Troubleshoot and fix immediately.

## 2. Documentation Updates (Mandatory)
Every task involving code changes MUST include a review and update of relevant documentation.

**Target Audiences:**
1. **DevOps**: Update 'infra/' docs, deployment guides, or artifactory instructions if infrastructure changes.
2. **System Developer**: Update 'docs/arch', 'README.md', or code comments if logic/patterns change.
3. **Frontend Developer**: Update component docs or API usage guides if UI/API changes.
4. **Quant/Data Team**: Update SDK docs ('libs/sdk_py'), Jupyter examples, or Model definitions if domain logic changes.

**Rule:**
- If you change how it works, you must change how it is documented.
- Check 'README.md' and 'docs/' hierarchy for stale information.

## 3. Technical Requirements (Testing)
- **Runner**: 'uv run pytest'
- **Database**: SQLite only (no Docker).
- **Asyncio**: Use session-scoped event loops and engine fixtures to avoid 'pytest-asyncio' scope errors.
- **Pragmas**: 'foreign_keys=OFF' for audit log resilience in tests.
