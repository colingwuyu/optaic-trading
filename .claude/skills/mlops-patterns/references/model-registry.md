# Model Registry Patterns

Model version management and stage transitions in OptAIC, with optional MLflow integration.

## Model Version Lifecycle

```
┌─────────┐     ┌──────────┐     ┌────────────┐     ┌──────────┐
│  None   │────►│  Staging │────►│ Production │────►│ Archived │
└─────────┘     └──────────┘     └────────────┘     └──────────┘
                     │                  │
                     └──────────────────┘
                      (rollback allowed)
```

## Model Version Model

```python
# libs/db/models/model_version.py
from sqlalchemy import Column, ForeignKey, String, LargeBinary, JSON, Enum
from sqlalchemy.dialects.postgresql import UUID
import enum

class ModelStage(str, enum.Enum):
    """Model version lifecycle stages."""
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"

class ModelVersion(Base):
    """A trained model artifact with versioning."""

    __tablename__ = "model_versions"

    id = Column(UUID(as_uuid=True), primary_key=True)
    model_instance_id = Column(UUID(as_uuid=True), ForeignKey("resources.id"), nullable=False)
    training_run_id = Column(UUID(as_uuid=True), ForeignKey("training_runs.id"), nullable=False)

    # Version identifier (semantic or auto-incremented)
    version = Column(String, nullable=False)  # e.g., "1.2.3" or "v42"

    # Artifact storage
    artifact_path = Column(String, nullable=True)  # Path in artifact store
    artifact_hash = Column(String, nullable=True)  # SHA256 of artifact

    # Stage
    stage = Column(Enum(ModelStage), default=ModelStage.STAGING)

    # Metrics at training time
    metrics = Column(JSON, nullable=True)
    hyperparams = Column(JSON, nullable=True)

    # Lineage
    input_dataset_versions = Column(JSON, nullable=True)  # List of dataset version IDs used

    # Metadata
    description = Column(String, nullable=True)
    tags = Column(JSON, nullable=True)  # {"experiment": "momentum_v2", "author": "colin"}

    # Timestamps
    created_at = Column(DateTime, nullable=False)
    promoted_at = Column(DateTime, nullable=True)  # When moved to production
    archived_at = Column(DateTime, nullable=True)
```

## Model Version Service

```python
# libs/core/domain/model_version_service.py
from typing import TYPE_CHECKING
from uuid import UUID

from libs.core.activity import record_activity_with_outbox
from libs.core.guardrails import GuardrailsEngine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

class ModelVersionService:
    """Manage model versions and stage transitions."""

    async def create(
        self,
        session: "AsyncSession",
        training_run_id: UUID,
        artifact: bytes,
        metrics: dict,
        hyperparams: dict,
        actor_id: UUID,
    ) -> "ModelVersion":
        """Create a new model version from training run."""

        # Get model instance from training run
        training_run = await self._get_training_run(session, training_run_id)

        # Generate version number
        version = await self._generate_version(session, training_run.model_instance_id)

        # Store artifact
        artifact_path, artifact_hash = await self._store_artifact(artifact)

        # Create version record
        version_record = ModelVersion(
            model_instance_id=training_run.model_instance_id,
            training_run_id=training_run_id,
            version=version,
            artifact_path=artifact_path,
            artifact_hash=artifact_hash,
            stage=ModelStage.STAGING,
            metrics=metrics,
            hyperparams=hyperparams,
            input_dataset_versions=training_run.input_dataset_versions,
        )

        session.add(version_record)
        await session.flush()

        # Emit activity
        await record_activity_with_outbox(
            session=session,
            actor_id=actor_id,
            resource_id=training_run.model_instance_id,
            action="model_version.created",
            payload={
                "version_id": str(version_record.id),
                "version": version,
                "stage": "staging",
                "metrics": metrics,
            },
        )

        return version_record

    async def promote_to_production(
        self,
        session: "AsyncSession",
        version_id: UUID,
        actor_id: UUID,
    ) -> "ModelVersion":
        """Promote a staging version to production."""

        version = await self._get_by_id(session, version_id)

        if version.stage != ModelStage.STAGING:
            raise ValueError(f"Cannot promote from stage: {version.stage}")

        # Validate via guardrails
        await GuardrailsEngine.validate_at_gate(
            gate="model.promote",
            resource_type="model_version",
            data={"version_id": str(version_id), "metrics": version.metrics},
            session=session,
        )

        # Archive current production version
        current_prod = await self._get_production_version(
            session, version.model_instance_id
        )
        if current_prod:
            current_prod.stage = ModelStage.ARCHIVED
            current_prod.archived_at = datetime.utcnow()

        # Promote new version
        version.stage = ModelStage.PRODUCTION
        version.promoted_at = datetime.utcnow()

        # Update model instance's active version
        model_instance = await self._get_model_instance(session, version.model_instance_id)
        model_instance.active_model_version_id = version_id

        # Emit activity
        await record_activity_with_outbox(
            session=session,
            actor_id=actor_id,
            resource_id=version.model_instance_id,
            action="model_version.promoted",
            payload={
                "version_id": str(version_id),
                "version": version.version,
                "previous_version_id": str(current_prod.id) if current_prod else None,
            },
        )

        return version

    async def rollback(
        self,
        session: "AsyncSession",
        model_instance_id: UUID,
        target_version_id: UUID,
        actor_id: UUID,
    ) -> "ModelVersion":
        """Rollback to a previous version."""

        target = await self._get_by_id(session, target_version_id)

        if target.stage == ModelStage.ARCHIVED:
            # Restore archived version to production
            target.stage = ModelStage.PRODUCTION
            target.archived_at = None
        elif target.stage == ModelStage.STAGING:
            # Promote staging to production
            target.stage = ModelStage.PRODUCTION
            target.promoted_at = datetime.utcnow()

        # Archive current production
        current_prod = await self._get_production_version(session, model_instance_id)
        if current_prod and current_prod.id != target_version_id:
            current_prod.stage = ModelStage.ARCHIVED
            current_prod.archived_at = datetime.utcnow()

        # Update model instance
        model_instance = await self._get_model_instance(session, model_instance_id)
        model_instance.active_model_version_id = target_version_id

        await record_activity_with_outbox(
            session=session,
            actor_id=actor_id,
            resource_id=model_instance_id,
            action="model_version.rollback",
            payload={
                "target_version_id": str(target_version_id),
                "target_version": target.version,
                "rolled_back_from": str(current_prod.id) if current_prod else None,
            },
        )

        return target
```

## MLflow Integration (Optional)

When `--with-mlflow` is enabled, sync versions to MLflow model registry.

```python
# libs/core/adapters/mlflow_registry.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mlflow

class MLflowRegistryAdapter:
    """Sync OptAIC model versions to MLflow."""

    def __init__(self, tracking_uri: str):
        import mlflow
        mlflow.set_tracking_uri(tracking_uri)
        self.client = mlflow.tracking.MlflowClient()

    async def register_version(
        self,
        model_version: "ModelVersion",
        model_instance_name: str,
    ) -> str:
        """Register model version in MLflow registry."""
        import mlflow

        # Create or get registered model
        try:
            self.client.create_registered_model(model_instance_name)
        except mlflow.exceptions.MlflowException:
            pass  # Already exists

        # Log model artifact
        with mlflow.start_run() as run:
            mlflow.log_params(model_version.hyperparams or {})
            mlflow.log_metrics(model_version.metrics or {})

            # Log artifact from path
            mlflow.log_artifact(model_version.artifact_path)

            # Register model version
            model_uri = f"runs:/{run.info.run_id}/model"
            mv = mlflow.register_model(model_uri, model_instance_name)

            # Add OptAIC metadata as tags
            self.client.set_model_version_tag(
                model_instance_name,
                mv.version,
                "optaic_version_id",
                str(model_version.id),
            )

            return mv.version

    async def transition_stage(
        self,
        model_instance_name: str,
        mlflow_version: str,
        stage: str,  # "Staging", "Production", "Archived"
    ):
        """Transition model stage in MLflow."""
        self.client.transition_model_version_stage(
            name=model_instance_name,
            version=mlflow_version,
            stage=stage,
        )
```

## Artifact Storage

```python
# libs/core/adapters/artifact_store.py
from abc import ABC, abstractmethod
from pathlib import Path
import hashlib

class ArtifactStoreAdapter(ABC):
    """Abstract artifact storage."""

    @abstractmethod
    async def put(self, artifact: bytes, key: str) -> str:
        """Store artifact, return path."""
        pass

    @abstractmethod
    async def get(self, path: str) -> bytes:
        """Retrieve artifact."""
        pass


class LocalArtifactStore(ArtifactStoreAdapter):
    """Local filesystem artifact store for embedded mode."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def put(self, artifact: bytes, key: str) -> str:
        """Store artifact locally."""
        # Hash for deduplication
        artifact_hash = hashlib.sha256(artifact).hexdigest()
        filename = f"{key}_{artifact_hash[:8]}.pkl"
        path = self.base_dir / filename

        path.write_bytes(artifact)
        return str(path)

    async def get(self, path: str) -> bytes:
        """Retrieve artifact."""
        return Path(path).read_bytes()


class S3ArtifactStore(ArtifactStoreAdapter):
    """S3/MinIO artifact store for production mode."""

    def __init__(self, bucket: str, endpoint_url: str | None = None):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", endpoint_url=endpoint_url)

    async def put(self, artifact: bytes, key: str) -> str:
        """Store artifact in S3."""
        import io
        self.s3.upload_fileobj(io.BytesIO(artifact), self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    async def get(self, path: str) -> bytes:
        """Retrieve artifact from S3."""
        import io
        # Parse s3:// path
        key = path.replace(f"s3://{self.bucket}/", "")
        buffer = io.BytesIO()
        self.s3.download_fileobj(self.bucket, key, buffer)
        return buffer.getvalue()
```

## SDK Usage

```python
from optaic import SDK

sdk = SDK()

# List model versions
versions = await sdk.mlops.list_versions(model_instance_id="...")

# Get production version
prod = await sdk.mlops.get_production_version(model_instance_id="...")

# Promote staging to production
await sdk.mlops.promote_version(version_id="...", reason="IC improved from 0.05 to 0.08")

# Rollback to previous version
await sdk.mlops.rollback(model_instance_id="...", target_version_id="...")

# Get version metrics history
history = await sdk.mlops.get_metrics_history(model_instance_id="...")
```
