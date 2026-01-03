---
description: Workflow to create a new domain resource (DB model + Service + API).
---

# Create Domain Resource Workflow

Follow this workflow when adding a new top-level Resource to the platform (e.g., Portfolio, signal, Dataset).

## 0. Determine Resource Tier

Identify which tier the resource belongs to:

| Tier | Description | Example |
|------|-------------|---------|
| Definition | Plugin/code reference | PipelineDef, OpDef |
| Instance | Configured usage | DatasetInstance, ModelInstance |
| Run | Execution activity | PipelineRun, TrainingRun |

## 1. Define Database Model
*   Create `libs/db/models/<name>.py`.
*   Inherit `Base`.
*   Add columns.
*   If it is a Resource, add FK to `resources.id`.
*   **For Instance types**: Include flow execution handles:
    *   `prefect_deployment_id` for single-flow
    *   Multiple handles for multi-flow (ModelInstance)
    *   External system IDs (mlflow_experiment_id, evidently_project_id)

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
*   **For Instance types**: In `create()`:
    *   Create Flow Execution Resource(s) (Prefect deployments)
    *   Store deployment IDs in extension table
    *   Register with external systems (MLflow, EvidentlyAI)
*   **For Instance types**: In `delete()`:
    *   Cleanup Flow Execution Resources
    *   Remove lineage edges

## 5. Register Resource
*   Update `libs/core/resources.py`: Add to `ResourceType`.

## 6. Implement Lineage (for Instance types)
*   In `create()`: Register lineage edges for upstream dependencies
*   Use `LineageResolver.add_lineage_edge()`

## 7. Unit Tests
*   Create `libs/core/tests/test_<name>.py`.
*   Test CRUD and constraints.
*   **For Instance types**: Test Flow Execution Resource creation.
*   Run: `pytest libs/core/tests/test_<name>.py`

