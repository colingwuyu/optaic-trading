# Prefect Integration Patterns

## Basic Flow Structure

```python
from prefect import flow, task
from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

@task(retries=3, retry_delay_seconds=60)
async def fetch_from_vendor(vendor: str, date: str) -> dict:
    """Fetch data with automatic retries."""
    async with VendorClient(vendor) as client:
        return await client.fetch(date)

@task
async def validate_data(data: dict, schema_ref: str) -> bool:
    """Validate against guardrails contract."""
    from optaic.guardrails import validate_contract
    report = await validate_contract("dataset.schema", data, schema_ref)
    return report.ok

@task
async def store_with_pit(
    data: dict,
    dataset_id: UUID,
    knowledge_date: datetime
) -> str:
    """Store data with PIT tracking. Returns version ID."""
    version = await DatasetStore.append(
        dataset_id=dataset_id,
        data=data,
        knowledge_date=knowledge_date
    )
    return version.id

@task
async def emit_refresh_activity(
    dataset_id: UUID,
    version_id: str,
    row_count: int
):
    """Emit activity event."""
    await record_activity_with_outbox(
        action="dataset.refreshed",
        resource_id=dataset_id,
        payload={
            "version_id": version_id,
            "row_count": row_count
        }
    )

@flow
async def daily_dataset_refresh(dataset_id: UUID, date: str):
    """Complete daily refresh flow."""
    # 1. Fetch
    raw = await fetch_from_vendor(vendor="bloomberg", date=date)

    # 2. Validate
    is_valid = await validate_data(raw, schema_ref="prices.v1")
    if not is_valid:
        await emit_refresh_activity(dataset_id, None, 0)  # Log failure
        raise ValueError("Schema validation failed")

    # 3. Store
    version_id = await store_with_pit(
        data=raw,
        dataset_id=dataset_id,
        knowledge_date=datetime.utcnow()
    )

    # 4. Emit activity
    await emit_refresh_activity(dataset_id, version_id, len(raw))

    return version_id
```

## Deployment Configuration

```python
# Create deployment with schedule
deployment = Deployment.build_from_flow(
    flow=daily_dataset_refresh,
    name="spx-ohlcv-daily",
    schedule=CronSchedule(
        cron="0 18 * * 1-5",  # 6pm weekdays
        timezone="America/New_York"
    ),
    parameters={
        "dataset_id": "uuid-here",
        "date": "{{date}}"  # Parameterized
    },
    work_pool_name="default"
)
```

## DAG Dependencies

```python
@flow
async def refresh_dag(as_of_date: str):
    """Refresh datasets in dependency order."""

    # Level 0: External data (no dependencies)
    spx_raw = await refresh_dataset.submit(
        dataset_id="spx-ohlcv",
        date=as_of_date
    )

    fred_raw = await refresh_dataset.submit(
        dataset_id="fred-gdp",
        date=as_of_date
    )

    # Level 1: Derived (depends on raw)
    momentum = await derive_signal.submit(
        dataset_id="spx-momentum",
        upstream_versions=[spx_raw],
        wait_for=[spx_raw]  # Explicit dependency
    )

    # Level 2: Combined (depends on multiple)
    composite = await derive_signal.submit(
        dataset_id="composite-signal",
        upstream_versions=[momentum, fred_raw],
        wait_for=[momentum, fred_raw]
    )

    return composite
```

## Error Handling

```python
from prefect import task
from prefect.states import Failed

@task
async def fetch_with_fallback(primary_vendor: str, fallback_vendor: str, date: str):
    """Try primary, fallback to secondary."""
    try:
        return await fetch_from_vendor(primary_vendor, date)
    except VendorError:
        return await fetch_from_vendor(fallback_vendor, date)

@flow
async def resilient_refresh(dataset_id: UUID, date: str):
    """Refresh with error handling."""
    try:
        version = await daily_dataset_refresh(dataset_id, date)
        return version
    except Exception as e:
        # Log failure activity
        await record_activity_with_outbox(
            action="dataset.refresh_failed",
            resource_id=dataset_id,
            payload={"error": str(e), "date": date}
        )
        raise
```

## OptAIC Adapter Integration

```python
from libs.core.dto import RunDTO

class PrefectOrchestratorAdapter:
    """Adapter between OptAIC and Prefect."""

    async def submit_run(self, instance_id: UUID, params: dict) -> RunDTO:
        """Submit run to Prefect."""
        from prefect.client import get_client

        async with get_client() as client:
            flow_run = await client.create_flow_run_from_deployment(
                deployment_id=self._get_deployment(instance_id),
                parameters=params
            )

        return RunDTO(
            id=uuid4(),
            resource_id=instance_id,
            status="submitted",
            orchestrator_kind="prefect",
            orchestrator_run_id=str(flow_run.id)
        )
```
