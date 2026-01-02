---
name: activity-logging
description: Follow these patterns when implementing activity emission and audit logging in OptAIC. Use for emitting ActivityEnvelopes on mutations (create, update, delete, execute), designing payloads, and ensuring audit compliance.
---

# Activity Logging Patterns

Guide for implementing audit-compliant activity emission in OptAIC services.

## When to Use

Apply when:
- Implementing service layer methods that mutate state
- Adding new domain resource operations (CRUD)
- Tracking execution events (runs, training, backtests)
- Implementing approval/promotion workflows
- Ensuring audit trail compliance

## Core Rule

> **If it changes state, it MUST emit an activity.**

All mutations must emit activities in the **service layer** (not API handlers or models).

## ActivityEnvelope

```python
ActivityEnvelope(
    tenant_id=UUID,
    actor_principal_id=UUID,
    resource_id=UUID,
    resource_type=str,           # "signal", "dataset", "portfolio"
    action=str,                  # "signal.created", "run.completed"
    visibility=str,              # "private"|"resource"|"scope"|"tenant"
    payload=dict,                # Action-specific data
    delivery_channels=list,      # Where to publish
    correlation_id=UUID          # Links related activities
)
```

## Action Naming

Use pattern: `<resource>.<verb>`

### Core Resource Actions
```
signal.registered    signal.validated     signal.promoted
dataset.created      dataset.previewed    dataset.refresh_started
dataset.refresh_completed dataset.refresh_failed
```

### Pipeline Actions
```
pipeline_def.submitted   pipeline_def.deployed
pipeline_instance.created pipeline.run_started pipeline.run_completed
```

### Experiment Actions
```
experiment.created   experiment.updated
experiment.run_completed experiment.run_failed
expression.evaluated macro.saved
```

### Run Lifecycle Actions
```
run.started          run.completed        run.failed          run.cancelled
backtest.started     backtest.completed   backtest.failed
training.started     training.completed   training.failed
inference.started    inference.completed  inference.failed
optimization.started optimization.completed optimization.failed
monitoring.started   monitoring.completed monitoring.alert
```

### Portfolio Actions
```
portfolio.rebalanced portfolio.constraints_updated
portfolio.weights_computed portfolio.optimization_started
```

### Promotion/Workflow Actions
```
promotion.requested  promotion.approved   promotion.merged    promotion.rejected
guardrails.validated guardrails.blocked   guardrails.warned
```

### Monitoring Actions
```
monitoring.drift_detected    monitoring.performance_alert
monitoring.data_quality_alert monitoring.threshold_breach
```

## Emission Patterns

### Simple Emission
```python
await record_activity_with_outbox(
    session=self.session,
    envelope=ActivityEnvelope(
        action="signal.created",
        actor_principal_id=self.actor_id,
        tenant_id=self.tenant_id,
        resource_id=resource.id,
        resource_type="signal",
        payload={"signal_type": dto.signal_type}
    )
)
```

### Transaction Wrapper
```python
from libs.core.activity import tx_activity

result, activity = await tx_activity(db, envelope, domain_fn)
```

## Payload Guidelines

**Include:** Changed fields, related IDs, computed metrics, status transitions
**Exclude:** Passwords, API keys, large blobs, PII beyond necessity

See [references/payload-examples.md](references/payload-examples.md).

## Correlation IDs

Link related activities in workflows:
```python
correlation_id = uuid4()

# Use same correlation_id throughout workflow
await emit("promotion.requested", correlation_id=correlation_id)
await emit("guardrails.validated", correlation_id=correlation_id)
await emit("promotion.merged", correlation_id=correlation_id)
```

## Reference Files

- [Payload Examples](references/payload-examples.md) - Example payloads by action type
- [Testing Activities](references/testing.md) - How to test activity emission
