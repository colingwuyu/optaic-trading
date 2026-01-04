---
name: sdk-e2e-testing
description: Strategy and patterns for designing and implementing End-to-End scenario tests using the Python SDK. Focuses on full-stack verification and SDK usability.
---

# E2E SDK Scenario Testing

This skill guides the design and implementation of end-to-end tests using the Python SDK.

## Goal
1.  **Verify System Correctness**: Test the full stack (SDK → API → Database).
2.  **Validate SDK Design**: Ensure the SDK is intuitive and user-friendly.

---

## Phase 1: Scenario Discovery

### 1. Identify Business Domain Features

Review the implemented features to identify testable scenarios. Map features to user workflows:

| Feature Area | User Workflow | SDK Methods |
|--------------|---------------|-------------|
| Data Pipelines | Ingest economic data | `pipelines.submit_definition()`, `pipelines.create_instance()` |
| Experiments | Explore expressions | `experiments.create()`, `experiments.run()` |
| Signals | Register alpha signals | `signals.create()`, `signals.validate()` |
| Resources | Organize work | `resources.create()`, `resources.move()` |
| RBAC | Control access | `rbac.grant_role()`, `rbac.list_grants()` |
| Chat | Collaborate | `chat.create_channel()`, `chat.send_message()` |
| Versioning | Track changes | `refs.create_branch()`, `refs.merge()` |

### 2. Design Case Study Scenarios

Each case study should represent a **coherent business workflow**, not isolated operations.

**Good Scenario Design:**
> "Quantitative Researcher Daily Workflow: Create project, run experiment, save macro, register signal, verify audit."

**Bad Scenario Design:**
> "Test Create Resource, Test Update Resource, Test Delete Resource" (Isolated operations)

### 3. Scenario Coverage Matrix

Ensure scenarios cover all dimensions:
*   **CRUD Operations** (Create, Read, Update, Delete)
*   **Business Logic** (Validation, status transitions)
*   **Cross-Resource** (Relationships, lineage)
*   **RBAC** (Permission checks)
*   **Audit** (Activity emission)
*   **Error Cases** (Invalid inputs, permission denied)

---

## Phase 2: Infrastructure & Patterns

Refer to the following references for implementation details:

- **[references/fixtures.md](references/fixtures.md)**: Standard `conftest.py` setup and `sdk_with_tenant` patterns.
- **[references/patterns.md](references/patterns.md)**: Code templates for `TestCaseStudy` classes, CRUD workflows, and Multi-user tests.

---

## Phase 3: SDK Design Feedback

### Capture Improvement Opportunities

Create a tracking section in test files to document:
1.  **Issues Found**: Missing fields, confusing names, inconsistent behavior.
2.  **Positive Patterns**: Things that work well.

### Improvement Workflow
1.  **Document** issue in comments.
2.  **Create** minimal repro test.
3.  **Propose** fix (schema change, new helper).
4.  **Implement** fix.
5.  **Verify**.

---

## Phase 4: Running Tests

```bash
# Run all E2E tests
uv run pytest tests/e2e/ -xvs

# Run specific case study
uv run pytest tests/e2e/test_case_studies.py::TestCaseStudy1_FREDEconomicData -xvs

# Run with coverage
uv run pytest tests/e2e/ --cov=libs/sdk_py --cov-report=term-missing
```

### Maintenance Rules
*   **No Mocks**: Use real SDK → API → DB.
*   **Independent Tests**: Each test creates its own data.
*   **Clean Assertions**: Assert business outcomes.
