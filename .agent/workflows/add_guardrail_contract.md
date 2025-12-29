---
description: Workflow to add a new guardrail contract kind (e.g. signal.bounds).
---

# Add Guardrail Contract Workflow

Follow this workflow to add a new validation contract type to the Guardrails Engine.

## 1. Design Contract
*   Decide on a unique `kind` string (e.g., `signal.bounds`).
*   Draft the JSON Schema for the configuration (e.g., min, max, allow_nan).

## 2. Register Contract Kind
*   Locate `libs/guardrails/registry.py` (actual path may vary, check codebase).
*   Register the kind and its default validator.

## 3. Implement Validator
*   Create a validator function/class that implements `ContractValidator`.
*   Input: `target_snapshot`, `contract_config`.
*   Output: `ValidationReport` or list of issues.
*   **Rule**: Must be pure and deterministic.

## 4. Add Tests
*   Create test in `libs/guardrails/tests/test_contracts.py`.
*   Test valid config + valid snapshot -> Pass.
*   Test invalid config -> Fail (Schema validation).
*   Test valid config + invalid snapshot -> Fail (Business validation).

## 5. Verify
*   Run: `pytest libs/guardrails/tests/`

