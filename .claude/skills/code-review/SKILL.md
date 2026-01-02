---
name: code-review
description: Use AUTOMATICALLY after completing any implementation task that modifies OptAIC platform code. Verifies activity logging in service layer, guardrails at lifecycle gates, two-tier resource model, PIT correctness, lazy imports, and DTO patterns. PROACTIVE - invoke after finishing code changes. (project)
---

# Code Review for OptAIC Platform Compliance

Skill for reviewing code to ensure it correctly adopts the OptAIC platform framework and patterns.

## IMPORTANT: Proactive Usage

**This skill should be invoked AUTOMATICALLY after completing any implementation task.** Do not wait for user request.

### Trigger Conditions (invoke automatically when)
1. You have just written or modified service layer code
2. You have implemented a new domain resource
3. You have written data pipeline or accessor code
4. You have extended the SDK (Python OR TypeScript)
5. You have modified frontend code (`apps/web`)
6. You have modified any file in the repo related to the active task

### How to Identify Files to Review
1. Check your recent edits - review ALL files you modified
2. Use `git diff --name-only`
3. **Include**: `.py`, `.ts`, `.tsx`, `.js`, `.json`

## When to Use

Apply when:
- **After completing any implementation task** (PROACTIVE)
- Reviewing new domain resource implementations
- Checking service layer code for compliance
- Validating SDKs (Py/TS) and Frontend components
- Verifying code meets specific requirements in `golden-wibbling-steele.md` (or valid plan)

## Critical Review Checklist

### 0. Plan / Requirement Verification (CRITICAL)

✅ Check:
- Does the code actually implement the requirements in the active plan?
- Are all fields/methods specified in the plan present?
- Are there gaps between the plan and the code?

### 1. Activity Logging (REQUIRED for all mutations)

✅ Check:
- Mutations emit `ActivityEnvelope` in **service layer**
- Action names follow `<resource>.<verb>` pattern
- Required fields present: `actor_principal_id`, `resource_id`, `resource_type`
- Payload includes changed fields, not sensitive data

❌ Flag if:
- Activity emitted in API handler or DB model
- Activity missing for create/update/delete operations

### 2. Guardrails Integration

✅ Check:
- Validation called at lifecycle gates (create/update/promote/run)
- `GuardrailsEngine.validate_at_gate()` called in service layer
- Reports stored and activity events emitted
- Enforcement respects staging (WARN) vs official (BLOCK)

### 3. Frontend & TypeScript Patterns

✅ Check:
- **Strict Types**: Interfaces defined for all data structures (No `any`).
- **ApiClient Usage**: Components use `ApiClient` methods, never direct `fetch`.
- **Hooks**: Logic encapsulated in custom hooks where appropriate.
- **Error Handling**: UI handles API errors gracefully.

❌ Flag if:
- Hardcoded URLs or IDs in frontend code.
- Direct `fetch` calls in components.
- Props drilling > 3 levels (use Context).

### 4. Two-Tier Resource Model

✅ Check:
- **Definitions**: Abstract interface, versioned, testable
- **Instances**: Config-as-code referencing `(def_id, def_version)`
- **Runs**: Executions that produce immutable versions

### 5. PIT (Point-in-Time) Correctness

✅ Check:
- `knowledge_date` tracked separately from `as_of_date`
- PIT queries include both date constraints
- No lookahead bias in data access

### 6. Lazy Import Pattern (Python)

✅ Check:
- Heavy deps (pandas, numpy, torch, pyarrow) use `TYPE_CHECKING`
- Runtime imports inside function bodies

### 7. DTO Pattern

✅ Check:
- Pydantic `BaseModel` for all DTOs
- SQLAlchemy models never exposed to API layer

## Review Workflow

1. **List all files modified** in this conversation or via `git diff --name-only`
2. **Read each modified file** using the Read tool
3. **Identify component type** (resource/service/pipeline/SDK)
4. **Apply relevant checklist items** from this skill
5. **Check blueprint alignment** (see `optaic_quant_platform_blueprint.md`)
6. **Flag violations with specific file:line references**
7. **Fix issues immediately** - do not just report, actually fix them
8. **Re-verify** after fixes

## Output Format

After review, produce a structured report:

```
## Code Review Report

### Files Reviewed
- `path/to/file1.py` - [component type]
- `path/to/file2.py` - [component type]

### Issues Found

#### ❌ [Severity] Issue in `file.py:line`
**Pattern Violated**: [Activity Logging | Guardrails | PIT | etc.]
**Problem**: [Description]
**Fix Applied**: [Yes/No - if Yes, describe the fix]

### Compliance Summary
- Activity Logging: ✅ Compliant / ❌ Issues found
- Guardrails Integration: ✅ Compliant / ❌ Issues found / ⚠️ N/A
- Two-Tier Resource Model: ✅ Compliant / ❌ Issues found / ⚠️ N/A
- PIT Correctness: ✅ Compliant / ❌ Issues found / ⚠️ N/A
- Lazy Imports: ✅ Compliant / ❌ Issues found
- DTO Pattern: ✅ Compliant / ❌ Issues found

### Recommendation
[PASS - ready for commit | NEEDS FIXES - list remaining issues]
```

## Reference Files

- [Review Checklist](references/checklist.md) - Detailed checklist by component
- [Anti-Patterns](references/anti-patterns.md) - Common mistakes to flag
- [Blueprint](../../optaic_quant_platform_blueprint.md) - Full platform specification
