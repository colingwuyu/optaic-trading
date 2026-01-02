---
trigger: model_decision
description: Agent trigger: Load this file when implementing side-effects that require audit logging.
---

# Audit Logging & Activity Events

OptAIC requires a strictly auditable trail for all resource mutations and critical actions.

## 1. The Activity Envelope

*   **Requirement**: Every Create, Update, Delete, or Execute action MUST emit an `ActivityEnvelope`.
*   **Model**: `libs.core.models.ActivityEnvelope`
*   **Fields**:
    *   `actor_id`: The Principal ID responsible.
    *   `action`: A dot-notation string (e.g., `resource.created`, `model.published`).
    *   `resource_type`: The type of resource affected.
    *   `resource_id`: The specific UUID.
    *   `payload`: A JSON-serializable dictionary with details.
    *   `metadata`: Contextual trace info (optional).

## 2. Emission Pattern

*   **Service Layer Only**: Emit events from the service/logic layer, NOT the API route handler and NOT the database model itself.
*   **Transactional**: Ideally, emit the event within the same logical unit of work (though implementation details may vary, e.g., using the `outbox` pattern if available).
*   **Method**: Use the standard `activity_service.emit()` or equivalent provided in the codebase.

## 3. Payload Requirements

*   **No Sensitive Data**: Do NOT include passwords, secrets, or huge binary blobs in the payload.
*   **Schema**: The payload should conform to a consistent shape for that `action` type.

## 4. Verification

*   **Test**: Verify that your service method calls the emitter.
*   **Check**: Ensure the `action` string follows the usage pattern `noun.verb`.

## 5. Standard Activity Actions (Quant Domain)

### Signal Operations
- `signal.registered` - Signal spec created from dataset
- `signal.validated` - Signal data validated against spec
- `signal.promoted` - Signal promoted to official

### Dataset Operations
- `dataset.previewed` - Dataset data previewed
- `dataset.refresh_started` - Dataset refresh began
- `dataset.refresh_completed` - Dataset refresh succeeded
- `dataset.refresh_failed` - Dataset refresh failed

### Pipeline Operations
- `pipeline_def.submitted` - Pipeline definition created
- `pipeline_def.deployed` - Pipeline definition deployed
- `pipeline_instance.created` - Pipeline instance created
- `pipeline.run_started` - Pipeline run started

### Experiment Operations
- `experiment.created` - Experiment created
- `experiment.updated` - Experiment updated
- `experiment.run_completed` - Experiment run succeeded
- `experiment.run_failed` - Experiment run failed
- `expression.evaluated` - Expression evaluated
- `macro.saved` - Experiment saved as macro