# Resource Operations Patterns

## Standard CRUD Operations

Every resource type implements standard operations:

```python
class DatasetsMixin:
    """Dataset CRUD operations."""

    # LIST - paginated with filters
    def list_datasets(
        self,
        parent_id: UUID,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None
    ) -> List[Dataset]:
        params = {
            "parent_id": str(parent_id),
            "limit": limit,
            "offset": offset
        }
        if status:
            params["status"] = status
        response = self._client.get("/api/v1/datasets", params=params)
        self._handle_response(response)
        return [Dataset.from_dict(d) for d in response.json()["items"]]

    # GET - single resource
    def get_dataset(self, dataset_id: UUID) -> Dataset:
        response = self._client.get(f"/api/v1/datasets/{dataset_id}")
        self._handle_response(response)
        return Dataset.from_dict(response.json())

    # CREATE - returns new resource
    def create_dataset(
        self,
        parent_id: UUID,
        name: str,
        pipeline_def_id: UUID,
        pipeline_config: dict,
        **kwargs
    ) -> Dataset:
        response = self._client.post(
            "/api/v1/datasets",
            json={
                "parent_id": str(parent_id),
                "name": name,
                "pipeline_def_id": str(pipeline_def_id),
                "pipeline_config": pipeline_config,
                **kwargs
            }
        )
        self._handle_response(response)
        return Dataset.from_dict(response.json())

    # UPDATE - partial update
    def update_dataset(
        self,
        dataset_id: UUID,
        **updates
    ) -> Dataset:
        response = self._client.patch(
            f"/api/v1/datasets/{dataset_id}",
            json=updates
        )
        self._handle_response(response)
        return Dataset.from_dict(response.json())

    # DELETE - soft delete
    def delete_dataset(self, dataset_id: UUID) -> None:
        response = self._client.delete(f"/api/v1/datasets/{dataset_id}")
        self._handle_response(response)
```

## Definition vs Instance Operations

Definitions and Instances have different operation patterns:

```python
# Definition operations - typically read-only for users
class PipelineDefsMixin:
    def list_pipeline_defs(
        self,
        space_id: UUID,
        kind: Optional[str] = None  # "etl", "expression", "training"
    ) -> List[PipelineDef]:
        """List available pipeline definitions."""
        params = {"space_id": str(space_id)}
        if kind:
            params["kind"] = kind
        response = self._client.get("/api/v1/pipeline-defs", params=params)
        self._handle_response(response)
        return [PipelineDef.from_dict(d) for d in response.json()["items"]]

    def get_pipeline_def(self, def_id: UUID, version: Optional[str] = None) -> PipelineDef:
        """Get pipeline definition, optionally specific version."""
        url = f"/api/v1/pipeline-defs/{def_id}"
        if version:
            url += f"/versions/{version}"
        response = self._client.get(url)
        self._handle_response(response)
        return PipelineDef.from_dict(response.json())


# Instance operations - full CRUD
class DatasetInstancesMixin:
    def create_dataset_instance(
        self,
        parent_id: UUID,
        name: str,
        pipeline: InstanceRef,
        store: InstanceRef,
        accessor: Optional[InstanceRef] = None,
        schedule: Optional[dict] = None
    ) -> DatasetInstance:
        """Create dataset instance from definitions."""
        response = self._client.post(
            "/api/v1/dataset-instances",
            json={
                "parent_id": str(parent_id),
                "name": name,
                "pipeline": pipeline.to_dict(),
                "store": store.to_dict(),
                "accessor": accessor.to_dict() if accessor else None,
                "schedule": schedule
            }
        )
        self._handle_response(response)
        return DatasetInstance.from_dict(response.json())
```

## Version Operations

```python
class VersionsMixin:
    def list_versions(
        self,
        resource_id: UUID,
        ref: str = "main",
        limit: int = 50
    ) -> List[Version]:
        """List versions on a branch."""
        response = self._client.get(
            f"/api/v1/resources/{resource_id}/versions",
            params={"ref": ref, "limit": limit}
        )
        self._handle_response(response)
        return [Version.from_dict(v) for v in response.json()["items"]]

    def get_version(
        self,
        resource_id: UUID,
        version_id: UUID
    ) -> Version:
        """Get specific version."""
        response = self._client.get(
            f"/api/v1/resources/{resource_id}/versions/{version_id}"
        )
        self._handle_response(response)
        return Version.from_dict(response.json())

    def get_version_at(
        self,
        resource_id: UUID,
        timestamp: datetime,
        ref: str = "main"
    ) -> Version:
        """Get version as of timestamp (PIT query)."""
        response = self._client.get(
            f"/api/v1/resources/{resource_id}/versions/at",
            params={
                "timestamp": timestamp.isoformat(),
                "ref": ref
            }
        )
        self._handle_response(response)
        return Version.from_dict(response.json())
```

## Run Operations

```python
class RunsMixin:
    def submit_run(
        self,
        instance_id: UUID,
        params: Optional[dict] = None
    ) -> Run:
        """Submit a run for execution."""
        response = self._client.post(
            f"/api/v1/instances/{instance_id}/runs",
            json={"params": params or {}}
        )
        self._handle_response(response)
        return Run.from_dict(response.json())

    def get_run(self, run_id: UUID) -> Run:
        """Get run status and details."""
        response = self._client.get(f"/api/v1/runs/{run_id}")
        self._handle_response(response)
        return Run.from_dict(response.json())

    def list_runs(
        self,
        instance_id: UUID,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Run]:
        """List runs for an instance."""
        params = {"instance_id": str(instance_id), "limit": limit}
        if status:
            params["status"] = status
        response = self._client.get("/api/v1/runs", params=params)
        self._handle_response(response)
        return [Run.from_dict(r) for r in response.json()["items"]]

    def cancel_run(self, run_id: UUID) -> Run:
        """Cancel a running execution."""
        response = self._client.post(f"/api/v1/runs/{run_id}/cancel")
        self._handle_response(response)
        return Run.from_dict(response.json())
```

## Governance Operations

```python
class GovernanceMixin:
    def request_promotion(
        self,
        resource_id: UUID,
        target_space: str,  # "staging" or "official"
        message: str
    ) -> PromotionRequest:
        """Request promotion to target space."""
        response = self._client.post(
            "/api/v1/promotion-requests",
            json={
                "resource_id": str(resource_id),
                "target_space": target_space,
                "message": message
            }
        )
        self._handle_response(response)
        return PromotionRequest.from_dict(response.json())

    def approve_promotion(
        self,
        request_id: UUID,
        comment: Optional[str] = None
    ) -> PromotionRequest:
        """Approve a promotion request."""
        response = self._client.post(
            f"/api/v1/promotion-requests/{request_id}/approve",
            json={"comment": comment}
        )
        self._handle_response(response)
        return PromotionRequest.from_dict(response.json())
```

## InstanceRef Pattern

For referencing definitions with configuration:

```python
@dataclass
class InstanceRef:
    """Reference to a definition with instance-specific config."""
    def_id: UUID
    def_version: Optional[str] = None  # None = latest
    config: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "def_id": str(self.def_id),
            "def_version": self.def_version,
            "config": self.config or {}
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InstanceRef":
        return cls(
            def_id=UUID(data["def_id"]),
            def_version=data.get("def_version"),
            config=data.get("config")
        )
```
