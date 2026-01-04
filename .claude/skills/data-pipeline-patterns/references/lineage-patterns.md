# Lineage and Freshness Patterns

Guide for implementing data lineage tracking and freshness checking in OptAIC.

## Core Architectural Principle

**CRITICAL**: Lineage DAG is built when Instances are CREATED, NOT at execution time.

- Build DAG at creation time
- Create subscriptions for pub/sub pattern
- Cache upstream IDs for fast execution checks

## Core Classes

Import from `libs/orchestration`:

```python
from libs.orchestration import (
    # Status and freshness
    DatasetStatus,        # Status enum
    UpdateFrequency,      # Expected update schedule
    FreshnessChecker,     # Calculate staleness
    FreshnessReport,      # Freshness report structure
    StatusStore,          # Execution metadata storage

    # Lineage resolution
    LineageResolver,      # Dependency traversal
    LineageDAG,           # DAG structure for visualization
    LineageFreshnessReport,
    UpstreamNotReadyError,

    # Pub/Sub pattern
    LineageObserver,      # Handles completion events
    CentrifugoNotifier,   # Real-time notifications
)
```

## DatasetStatus Enum

```python
class DatasetStatus(str, Enum):
    NOT_INITIALIZED = "not_initialized"  # No data exists yet
    READY = "ready"                       # Current and valid
    STALE = "stale"                       # Outdated, needs refresh
    STALE_SOURCE_DELAYED = "stale_source_delayed"  # Source has no new data
    ERROR = "error"                       # Pipeline failed
```

## Freshness Calculation

```python
checker = FreshnessChecker(status_store)

# Calculate single resource status
status = await checker.calculate_staleness(
    session,
    resource_id,
    as_of=date.today(),
)

# Calculate with all upstream dependencies
report = await checker.check_composite_freshness(
    session,
    resource_id,
)
print(f"All ready: {report.all_ready}")
print(f"Blocking: {report.blocking_resources}")
```

## UpdateFrequency Configuration

Controls how "freshness" is calculated:

| Frequency | Expected Date Logic |
|-----------|---------------------|
| `daily` | Yesterday (or prev business day) |
| `weekly` | Previous occurrence of `day_of_week` |
| `monthly` | Last day of previous month |
| `quarterly` | Last day of previous quarter |
| `irregular` | No expected date (always fresh if data exists) |

```python
# Daily financial data (T+1)
UpdateFrequency(
    frequency="daily",
    business_days_only=True,
    grace_period_days=1,  # Allow 1 day delay
)

# Weekly strategy rebalance on Monday
UpdateFrequency(
    frequency="weekly",
    day_of_week=0,  # Monday
)

# Monthly performance reports
UpdateFrequency(
    frequency="monthly",
    grace_period_days=5,  # Allow 5 days into new month
)
```

## Lineage Resolution

```python
resolver = LineageResolver()

# Get all upstream dependencies (recursive)
upstreams = await resolver.resolve_upstream_dependencies(
    session, resource_id, recursive=True
)

# Get all downstream dependents
downstreams = await resolver.resolve_downstream_dependencies(
    session, resource_id, recursive=True
)

# Get execution order as parallelizable batches
batches = await resolver.get_execution_order(session, root_id)
# [[level-0-ids], [level-1-ids], [level-2-ids], ...]
```

## Pre-Execution Freshness Check

```python
async def execute_with_freshness_check(
    session, dataset_id, force=False
):
    resolver = LineageResolver()
    checker = FreshnessChecker(status_store)

    # Check all upstreams
    report = await resolver.check_upstream_freshness(
        session, dataset_id, checker
    )

    if not report.all_ready:
        if force:
            logger.warning(f"Force executing despite stale: {report.blocking_resources}")
        else:
            raise UpstreamNotReadyError(
                f"{len(report.blocking_resources)} upstream(s) not ready",
                blocking_resources=report.blocking_resources,
            )

    # Proceed with execution
    ...
```

## Staleness Propagation

When a resource's data changes, mark downstream as stale:

```python
async def on_dataset_refreshed(session, dataset_id):
    resolver = LineageResolver()

    # Mark all downstream resources as stale
    affected = await resolver.propagate_staleness(session, dataset_id)

    logger.info(f"Marked {len(affected)} downstream resources as stale")

    # Optionally trigger downstream refresh
    for downstream_id in affected:
        await schedule_refresh(downstream_id)
```

## Lineage DAG at Instance Creation

When creating a DatasetInstance, build the lineage DAG and create subscriptions:

```python
async def create_dataset_instance(session, payload, actor):
    # 1. Create the dataset instance
    instance = await create_instance(session, payload, actor)

    # 2. Build lineage DAG from pipeline config (CREATION TIME)
    resolver = LineageResolver()
    dag = await resolver.build_dag_for_instance(
        session, instance.resource_id, actor.tenant_id
    )

    # 3. Cache upstream IDs for fast execution checks
    if dag.has_dependencies:
        instance.upstream_resource_ids = [str(uid) for uid in dag.upstream_ids]
        instance.upstream_status = {str(uid): "unknown" for uid in dag.upstream_ids}

        # 4. Create DatasetLineage + Subscription records (pub/sub)
        await resolver.create_lineage_and_subscriptions(session, dag)

    return instance
```

## Pub/Sub Observer Pattern

Downstream datasets are notified when upstreams complete via the observer pattern:

```python
from libs.orchestration import LineageObserver, CentrifugoNotifier

async def on_pipeline_run_completed(session, run):
    observer = LineageObserver()

    # 1. Notify all downstreams that this upstream completed
    # Returns list of downstreams that are now fully ready
    ready_ids = await observer.on_upstream_completed(
        session,
        upstream_id=run.dataset_instance_id,
        run_id=run.resource_id,
    )

    # 2. Publish real-time notifications to Centrifugo
    notifier = CentrifugoNotifier()
    for downstream_id in ready_ids:
        await notifier.notify_upstream_ready(
            downstream_id=downstream_id,
            upstream_id=run.dataset_instance_id,
            all_ready=True,
        )

async def on_pipeline_run_failed(session, run, error):
    observer = LineageObserver()

    # Mark upstream as "error" in all downstreams
    affected_ids = await observer.on_upstream_failed(
        session,
        upstream_id=run.dataset_instance_id,
        run_id=run.resource_id,
        error=error,
    )

    # Notify downstreams of failure
    notifier = CentrifugoNotifier()
    for downstream_id in affected_ids:
        await notifier.notify_upstream_failed(downstream_id, run.dataset_instance_id, error)
```

## Fast Execution Check (Cached Status)

Use cached `upstream_status` for execution checks (no lineage query needed):

```python
async def check_can_execute(session, instance_id, force=False):
    resolver = LineageResolver()

    # Fast check from cached status
    all_ready = await resolver.check_all_upstreams_ready(session, instance_id)

    if not all_ready and not force:
        raise UpstreamNotReadyError(f"Upstream dependencies not ready")

    return True
```

## Edge Types

| Edge Kind | Description |
|-----------|-------------|
| `data_dependency` | Downstream uses upstream's data |
| `schema_dependency` | Downstream depends on upstream's schema |
| `feature_dependency` | Model depends on feature dataset |
| `signal_dependency` | Backtest depends on signal |

## Lineage Graph Visualization

```python
# Get graph for visualization
graph = await resolver.get_lineage_graph(
    session,
    resource_id,
    direction="both",  # "upstream", "downstream", or "both"
)

# Returns:
{
    "nodes": [
        {"id": "uuid", "name": "Dataset A", "type": "DatasetInstance", "direction": "upstream"},
        {"id": "uuid", "name": "Signal B", "type": "SignalInstance", "direction": "downstream"},
    ],
    "edges": [
        {"source": "uuid-a", "target": "uuid-b", "kind": "data_dependency"},
    ],
    "center_id": "uuid"
}
```

## StatusStore Integration

Track execution metadata for freshness calculations:

```python
# On pipeline start
await status_store.mark_run_start(dataset_id)

# On success
await status_store.mark_run_success(
    dataset_id,
    last_data_date=date(2024, 1, 15),
    rows_processed=10000,
)

# On failure
await status_store.mark_run_error(
    dataset_id,
    error_message="Connection timeout",
)

# Get current status
status_record = await status_store.get_status(dataset_id)
```

## Smart Execution Modes

| Mode | Behavior |
|------|----------|
| `force=True` | Run regardless of freshness, ignore upstream status |
| `smart=True` | Skip if already fresh, run only stale nodes |
| `recursive=True` | Refresh stale upstreams before running |

```python
async def smart_refresh(session, dataset_id, recursive=False):
    checker = FreshnessChecker(status_store)
    status = await checker.calculate_staleness(session, dataset_id)

    if status == DatasetStatus.READY:
        logger.info("Already fresh, skipping")
        return

    if recursive:
        # Refresh stale upstreams first
        resolver = LineageResolver()
        batches = await resolver.get_execution_order(session, dataset_id)
        for batch in batches:
            await asyncio.gather(*[
                refresh_if_stale(session, rid)
                for rid in batch
            ])

    await execute_refresh(dataset_id)
```
