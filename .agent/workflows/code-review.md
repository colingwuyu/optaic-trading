---
description: Review uncommitted code for OptAIC platform compliance (activity logging, guardrails, etc.)
---

1. Identify files to review:
   - Run `git status` and `git diff --name-only` to find modified or new files (staged + unstaged).
   - Also consider files modified in the current user session.
   - **Scope**: Include ALL relevant files (`.py`, `.ts`, `.tsx`, `.js`, `.json`) in `libs/`, `apps/api/`, `apps/web/`, `apps/worker/`.

// turbo
2. Contextualize Review:
   - Check if there is an active plan/task file (e.g., `golden-wibbling-steele.md`).
   - Read specific requirements/objectives from that plan to ensure functional compliance.
   - For each identified file, read the content using `view_file`.

3. Perform a critical review based on the OptAIC Platform Compliance Checklist:
   - **Functional Compliance**: Does the code meet the specific Phase/Task requirements defined in the plan?
   - **Backend (Python)**:
     - **Activity Logging**: Service layer mutations MUST emit `ActivityEnvelope`.
     - **Guardrails**: Lifecycle gates (create/update/promote) MUST call `GuardrailsEngine`.
     - **PIT Correctness**: Data accessors MUST handle `knowledge_date` vs `as_of_date`.
     - **Lazy Imports**: Heavy deps MUST be lazy-loaded.
   - **Frontend (TypeScript/React)**:
     - **Type Safety**: No `any`; proper interfaces defined.
     - **API Patterns**: Use `ApiClient` methods, not raw `fetch`.
     - **Components**: Functional components + Hooks pattern.
   - **SDK (Python/TS)**:
     - **Consistency**: Python and TS SDKs should offer equivalent functionality where applicable.
     - **Lazy Loading**: Client properties should be lazy-loaded.

4. Output a structured report with the following sections:
   - Files Reviewed
   - Plan Alignment (Does it meet the specific task requirements?)
   - Issues Found (with file:line references)
   - Compliance Summary (Pass/Fail for validation categories)
   - Recommendation (Pass/Needs Fixes)

5. If critical issues are found, ask the user if they would like you to fix them.
