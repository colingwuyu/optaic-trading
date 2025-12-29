---
description: Workflow to create a new domain resource (DB model + Service + API).
---

# Create Domain Resource Workflow

Follow this workflow when adding a new top-level Resource to the platform (e.g., Portfolio, signal, Dataset).

## 1. Define Database Model
*   Create `libs/db/models/<name>.py`.
*   Inherit `Base`.
*   Add columns.
*   If it is a Resource, add FK to `resources.id`.

## 2. Define DTOs
*   Create/Update `libs/core/<name>.py` (or similar).
*   Define `ReadDTO`, `CreateDTO`, `UpdateDTO`.

## 3. Generate Migration
*   Run: `optaic db revision --autogenerate -m "add <name>"`
*   Review the generated file in `libs/db/migrations/`.

## 4. Implement Service Layer
*   Create `libs/core/services/<name>_service.py` (or similar location).
*   Implement CRUD:
    *   `create()`: Persist to DB -> Emit `<name>.created` activity.
    *   `update()`: Persist -> Emit `<name>.updated`.
    *   `delete()`: Soft delete (if applicable) -> Emit `<name>.deleted`.

## 5. Register Resource
*   Update `libs/core/resources.py`: Add to `ResourceType`.

## 6. Unit Tests
*   Create `libs/core/tests/test_<name>.py`.
*   Test CRUD and constraints.
*   Run: `pytest libs/core/tests/test_<name>.py`

