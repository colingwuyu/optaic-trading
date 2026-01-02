---
description: Generate, validate, and run general unit tests for code
---

1. Analyze the target code (user specified or uncommitted changes).
   - Identify public methods, branching logic, and edge cases.
   - Determine dependencies and mocking needs.
   - Find out test suite gap from uncomitted implementation.
   - Think hard to find the must to have tests in order to meeting user's requirements of the code implementation
   - Ensure unit tests are grounded on data that is realistic, meaningful instead of mocking data
   - Unit tests coverage of the new code implementation has to be at least 90%

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