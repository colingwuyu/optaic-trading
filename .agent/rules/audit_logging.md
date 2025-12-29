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