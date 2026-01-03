# Orchestration Library

The `libs.orchestration` package provides the core infrastructure for executing, tracking, and managing "Runs" within the OptAIC platform.

## Overview

This package implements the **Execution Orchestration Infrastructure** (Phase 2.7), serving as the foundational engine that powers:
- **Pipeline Runs** (Data ingestion/transformation)
- **Experiment Runs** (Expression evaluation previews)
- **Backtest Runs** (Strategy simulation)
- **Training/Inference Runs** (MLOps)

It bridges the gap between the static **Resource Model** (Definitions/Instances) and the dynamic **Execution Environment** (Compute).

## Key Components

### 1. RunExecutionService (`run_service.py`)
The central coordinator for all execution activities.
- **Responsibilities**:
  - Creates Run resources with proper governance (RBAC, parent lineage).
  - Validates operations via `GuardrailsEngine` at lifecycle gates.
  - Resolves dependency graphs from dataset/experiment instances.
  - Submits flows to the configured `OrchestratorAdapter`.
  - Polls for status updates and syncs them to the DB.
  - Emits `ActivityEnvelope` events for audit trails.
  
### 2. Orchestrator Adapters (`adapter.py`, `local.py`, `prefect_adapter.py`)
Abstracts the underlying execution backend.
- **`OrchestratorAdapter`**: Abstract base class defining the interface (`submit_run`, `get_status`, `cancel_run`).
- **`LocalOrchestrator`**: In-process executor using `asyncio` and `graphlib`. Ideal for development and simple tasks.
- **`PrefectOrchestrator`**: Adapter for Prefect (2.x/3.x), enabling scalable, distributed execution.

### 3. Dependency DAGs (`dag.py`, `lineage.py`)
Tools for building and analyzing execution graphs.
- **`build_graph`**: Constructs a deployable flow definition from a root resource, traversing upstream dependencies.
- **`LineageResolver`**:  Resolves the full ancestry of a dataset/model to ensure correctness and PIT (Point-in-Time) consistency.

### 4. Status Tracking (`status_store.py`)
A dedicated store for granular execution metadata.
- Tracks `last_run_status`, `rows_processed`, `last_data_date`, etc.
- Used to make fast decisions about whether to skip or re-run a pipeline (incremental processing).

### 5. Freshness Checks (`freshness.py`)
Logic to determine if a dataset is "stale" based on its upstream dependencies and schedule.

## Usage Example

```python
from libs.orchestration.run_service import RunExecutionService
from libs.orchestration.local import LocalOrchestrator
from libs.orchestration.status_store import StatusStore

# Initialize service
service = RunExecutionService(
    orchestrator=LocalOrchestrator(),
    status_store=StatusStore(session),
    guardrails_engine=guardrails_engine, # Optional
)

# Submit a pipeline run
result = await service.submit_pipeline_run(
    session=session,
    actor=actor,
    dataset_id=dataset_id,
    mode="incremental"
)

# Poll for completion
status = await service.poll_and_sync(session, run_id=result["id"])
print(status)
```
