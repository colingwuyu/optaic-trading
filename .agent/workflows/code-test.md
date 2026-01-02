---
description: Generate and run framework compliance tests for uncommitted code
---

1. Identify files to test:
   - Run `git status` and `git diff --name-only` to find modified or new files that are not yet committed.
   - Focus on service layer, pipelines, SDK extensions, and DTOs.

2. Generate compliance tests for the identified files:
   - **Activity Emission**: Create tests to verify `ActivityEnvelope` emission for mutations.
   - **Guardrails**: Create tests to verify validation at lifecycle gates.
   - **PIT Correctness**: Create tests for data accessors to ensure no lookahead bias.
   - **DTO Serialization**: Create tests for any new Pydantic models.
   - **Lazy Imports**: Create tests to verify heavy dependencies aren't imported at module level.
   - Find out test suite gap from uncomitted implementation.
   - Think hard to find the must to have tests in order to meeting user's requirements of the code implementation
   - Ensure unit tests are grounded on data that is realistic, meaningful instead of mocking data
   - Unit tests coverage of the new code implementation has to be at least 90%

3. Write the test files to the appropriate `tests/` directory (mirrored structure).
   - Use standard naming: `test_<module>_activity.py`, `test_<module>_guardrails.py`, etc., or add to existing test files.
   - tests folders are binded with the corresponding module, and name the test intuitively for developers

4. Run the newly created tests using `uv run pytest <test_file>`.

5. Analyze results:
   - If tests fail, analyze the cause.
   - Fix the test or the source code as appropriate.
   - Never cheat by modifying tests with mocking data and domain-irrelevant data in order to pass the tests.
   - Re-run tests until passing.

6. Report the coverage and status to the user.