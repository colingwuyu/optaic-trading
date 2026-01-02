---
description: Generate and run framework compliance tests for uncommitted code
---

1. Identify files to test:
   - Run `git status` and `git diff --name-only` to find modified or new files.
   - Scope: Service layer (`.py`), SDKs (`.py`, `.ts`), Frontend (`.tsx`), Utilities.

2. Generate/Refine tests for the identified files:
   - **Backend (Python)**:
     - Activity Emission, Guardrails, PIT Correctness, DTOs.
     - Coverage target: >90% for logic.
   - **Frontend/SDK (TypeScript)**:
     - Unit tests for logic/utils (`vitest`/`jest`).
     - Type checking (`tsc --noEmit`) for correctness.
   - **Plan Alignment**: Ensure tests cover the *functional requirements* of the active task/plan.
   - **Strategy**: Use realistic data; avoid excessive mocking of domain logic.

3. Write the test files to the appropriate `tests/` directory (mirrored structure).
   - Python: `tests/test_<module>.py`
   - TypeScript: `src/__tests__/` or `*.test.ts` alongside code.

4. Run the tests:
   - Python: `uv run pytest <test_file>`
   - TypeScript: `npm run typecheck` AND `npm test` (in relevant package).

5. Analyze results:
   - If tests fail, analyze the cause.
   - Fix the test or the source code as appropriate.
   - Never cheat by modifying tests with mocking data and domain-irrelevant data in order to pass the tests.
   - Re-run tests until passing.

6. Report the coverage and status to the user.