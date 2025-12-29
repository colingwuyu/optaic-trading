---
trigger: always_on
---

# Unit Test Requirements Policy

## All Tasks Must Pass Unit Tests
The agent must ensure that all code implementations and resulting tasks, excluding pure documentation updates, have passing unit tests before reporting completion to the user.

- **Pre-report verification:** Always run the project's test suite as a final step.
- **Do not proceed if tests fail:** If tests fail, the agent must troubleshoot and fix the failures before considering the task complete.

## Zero Warnings Policy
All tests must not only pass, but also execute without any warnings (e.g., deprecation warnings, linting warnings, compiler warnings).

- **Warning Resolution:** If any warnings occur during the test run or compilation, the agent is responsible for resolving them as if they were errors.
- **Clean Output:** The final report to the user must confirm that the test output is entirely clean of warnings and errors.
