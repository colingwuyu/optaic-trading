---
description: Generate, validate, and run general unit tests for code
---

1. Analyze the target code (user specified or uncommitted changes).
   - Identify language (Python, TypeScript/JS) and framework.
   - **Requirement Check**: Read the active plan/task (e.g. `golden-wibbling-steele.md`) to understand *what* needs testing.
   - Identify public methods, branching logic, and critical paths.
   - **Gap Analysis**: Compare existing tests against requirements.
   - **Quality Standard**:
     - Realistic data (minimal mocking of values).
     - >90% coverage for new logic.
     - Tests must prove the *requirements* are met.

2. Check for existing tests to avoid duplication.

3. Generate unit tests following project standards:
   - Use `pytest` for Python, `jest`/`vitest` for JS/TS.
   - Put tests in `tests/` directory or alongside code as per project convention.
   - Follow AAA (Arrange-Act-Assert) pattern.
   - Cover happy paths, edge cases, error handling, and null inputs.

4. Write the test files.

5. Run the tests:
   - Python: `uv run pytest <path>`
   - JS: `npm test` or equivalent.

6. Verify results:
   - **Zero Warnings**: Fix deprecation or lint warnings.
   - **All Pass**: Do not report completion until tests pass.
   - If tests fail, fix the tests or report code bugs.

7. Output a summary of tests created and results.