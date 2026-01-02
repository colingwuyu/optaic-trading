---
description: Review uncommitted code for OptAIC platform compliance (activity logging, guardrails, etc.)
---

1. Identify files to review:
   - Run `git status` and `git diff --name-only` to find modified or new files that are not yet committed.
   - Also consider files modified in the current user session.
   - Focus on `.py` files in `libs/core/`, `libs/db/`, `apps/api/`, `libs/sdk_py/`.

// turbo
2. For each identified file, read the content using `view_file` (or `read_file` if available).

3. Perform a critical review based on the OptAIC Platform Compliance Checklist:
   - **Activity Logging**: Ensure all mutations (create/update/delete) emit `ActivityEnvelope` in the service layer. Checks for `action` names, `actor_principal_id`, and payload safety.
   - **Guardrails Integration**: Ensure `GuardrailsEngine.validate_at_gate()` is called for lifecycle gates (create/update/promote/run).
   - **Two-Tier Resource Model**: Verify separation of Definitions and Instances.
   - **PIT Correctness**: Check that `knowledge_date` is tracked separately from `as_of_date` in data accessors.
   - **Lazy Import Pattern**: Ensure heavy dependencies (pandas, torch, etc.) are imported lazily or inside type checking blocks.
   - **DTO Pattern**: Verify Pydantic usage and that SQLAlchemy models are not exposed to the API.

4. Output a structured report with the following sections:
   - Files Reviewed
   - Issues Found (with file:line references)
   - Compliance Summary (Pass/Fail for each category)
   - Recommendation (Pass/Needs Fixes)

5. If critical issues are found, ask the user if they would like you to fix them.
