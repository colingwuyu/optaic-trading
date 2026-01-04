"""Pipeline Service - Pipeline Definition and Instance Management.

This service handles:
- Submitting pipeline definitions (plugins)
- Creating pipeline instances (configurations)
- Triggering pipeline runs
- Managing pipeline lifecycle (draft → deployed)

The code_ref field links PipelineDefinition to PIPELINE_FACTORY implementations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import (
    ActivityEnvelope,
    record_activity_with_outbox,
    tx_activity,
)
from libs.core.rbac.models import ActorContext
from libs.data.registry import PIPELINE_FACTORY
from libs.db.models.quant import (
    PipelineDefinition,
    PipelineInstance,
)
from libs.db.models.resource import Resource

if TYPE_CHECKING:
    pass


class PipelineService:
    """Service for pipeline operations.

    Pipelines are the data ingestion layer:
    - Definitions: Reusable ETL code (FRED, Bloomberg, Expression, etc.)
    - Instances: Configured pipelines with schedules and parameters
    - Runs: Executions that refresh datasets
    """

    async def submit_definition(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        code_ref: str,
        category: str,
        parent_id: UUID,
        interface_spec: str = "libs.data.pipelines.base.BasePipeline",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        parameters_schema: dict[str, Any] | None = None,
        guardrail_contracts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit a new pipeline definition.

        Creates a PipelineDefinition resource in draft status.
        Must be deployed before it can be used to create instances.

        Args:
            session: Database session
            actor: Actor context
            name: Definition name
            code_ref: Factory registration key (e.g., "ExpressionPipeline")
            category: Pipeline category (etl, expression, etc.)
            parent_id: Parent resource (Space)
            interface_spec: Interface specification
            input_schema: Input schema definition
            output_schema: Output schema definition
            parameters_schema: Parameters schema
            guardrail_contracts: Contracts to enforce

        Returns:
            Pipeline definition info
        """
        # Validate code_ref exists in factory
        if code_ref not in PIPELINE_FACTORY:
            raise ValueError(
                f"code_ref '{code_ref}' not registered in PIPELINE_FACTORY"
            )

        resource_id = uuid4()

        async def domain_fn(sess: AsyncSession) -> Resource:
            # Create Resource first
            resource = Resource(
                id=resource_id,
                tenant_id=actor.tenant_id,
                type="PipelineDef",
                parent_id=parent_id,
                owner_principal_id=actor.id,
                name=name,
                space_kind="team",
                subspace_kind="staging",
                status="draft",
                metadata_json={"category": category},
            )
            sess.add(resource)
            # Flush Resource first to satisfy FK constraint on PipelineDefinition
            await sess.flush()

            # Create Extension (references resource_id FK)
            definition = PipelineDefinition(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                category=category,
                interface_spec=interface_spec,
                code_ref=code_ref,
                input_schema=input_schema or {},
                output_schema=output_schema or {},
                parameters_schema=parameters_schema or {},
                compatibility_rules={},
                guardrail_contracts=guardrail_contracts or [],
            )
            sess.add(definition)
            await sess.flush()
            return resource

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type="PipelineDef",
            action="pipeline_def.submitted",
            payload={
                "name": name,
                "code_ref": code_ref,
                "category": category,
            },
        )
        resource, _ = await tx_activity(session, envelope, domain_fn)

        return {
            "id": str(resource_id),
            "name": name,
            "code_ref": code_ref,
            "category": category,
            "status": "draft",
        }

    async def deploy_definition(
        self,
        session: AsyncSession,
        actor: ActorContext,
        definition_id: UUID,
    ) -> dict[str, Any]:
        """Deploy a pipeline definition.

        Changes status from draft to active, allowing instance creation.

        Args:
            session: Database session
            actor: Actor context
            definition_id: Pipeline definition resource ID

        Returns:
            Deployment status
        """
        resource = await session.get(Resource, definition_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"PipelineDefinition {definition_id} not found")

        if resource.status != "draft":
            raise ValueError(
                f"Cannot deploy: status is '{resource.status}', expected 'draft'"
            )

        definition = await session.get(PipelineDefinition, definition_id)
        if not definition:
            raise ValueError(f"PipelineDefinition extension {definition_id} not found")

        # Update status
        resource.status = "active"
        await session.flush()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=definition_id,
            resource_type="PipelineDef",
            action="pipeline_def.deployed",
            payload={"code_ref": definition.code_ref},
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(definition_id),
            "name": resource.name,
            "code_ref": definition.code_ref,
            "status": "active",
        }

    async def create_instance(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        definition_id: UUID,
        parent_id: UUID,
        config: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a pipeline instance from a definition.

        Args:
            session: Database session
            actor: Actor context
            name: Instance name
            definition_id: Pipeline definition to instantiate
            parent_id: Parent resource (Project)
            config: Instance configuration
            schedule: Schedule configuration

        Returns:
            Pipeline instance info
        """
        # Load and validate definition
        definition = await session.get(PipelineDefinition, definition_id)
        if not definition or definition.tenant_id != actor.tenant_id:
            raise ValueError(f"PipelineDefinition {definition_id} not found")

        def_resource = await session.get(Resource, definition_id)
        if def_resource.status != "active":
            raise ValueError(f"Definition must be active, got '{def_resource.status}'")

        resource_id = uuid4()

        async def domain_fn(sess: AsyncSession) -> Resource:
            # Create Resource first
            resource = Resource(
                id=resource_id,
                tenant_id=actor.tenant_id,
                type="PipelineInstance",
                parent_id=parent_id,
                owner_principal_id=actor.id,
                name=name,
                space_kind="team",
                subspace_kind="staging",
                status="active",
                metadata_json={},
            )
            sess.add(resource)
            # Flush Resource first to satisfy FK constraint on PipelineInstance
            await sess.flush()

            # Create Extension (references resource_id FK)
            instance = PipelineInstance(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                definition_resource_id=definition_id,
                config_json=config or {},
                schedule_json=schedule or {},
                status="idle",
            )
            sess.add(instance)
            await sess.flush()
            return resource

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type="PipelineInstance",
            action="pipeline_instance.created",
            payload={
                "name": name,
                "definition_id": str(definition_id),
                "code_ref": definition.code_ref,
            },
        )
        resource, _ = await tx_activity(session, envelope, domain_fn)

        return {
            "id": str(resource_id),
            "name": name,
            "definition_id": str(definition_id),
            "code_ref": definition.code_ref,
            "status": "idle",
        }

    async def trigger_run(
        self,
        session: AsyncSession,
        actor: ActorContext,
        instance_id: UUID,
        *,
        run_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger a pipeline run.

        Args:
            session: Database session
            actor: Actor context
            instance_id: Pipeline instance to run
            run_config: Optional run-specific configuration

        Returns:
            Run submission info
        """
        instance = await session.get(PipelineInstance, instance_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"PipelineInstance {instance_id} not found")

        # Load definition to get code_ref
        definition = await session.get(
            PipelineDefinition, instance.definition_resource_id
        )
        if not definition:
            raise ValueError("Pipeline definition not found")

        # Build pipeline from factory
        _pipeline = PIPELINE_FACTORY.build(
            definition.code_ref,
            resource_id=str(instance_id),
            config=instance.config_json or {},
        )

        # Update instance status
        instance.status = "running"
        instance.last_run_at = datetime.now(timezone.utc)
        await session.flush()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=instance_id,
            resource_type="PipelineInstance",
            action="pipeline.run_started",
            payload={
                "code_ref": definition.code_ref,
                "run_config": run_config or {},
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        # In a real system, this would queue the run
        # For now, return submission info
        return {
            "instance_id": str(instance_id),
            "code_ref": definition.code_ref,
            "status": "running",
            "message": "Run queued for execution",
        }

    async def list_definitions(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        category: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List pipeline definitions.

        Args:
            session: Database session
            actor: Actor context
            category: Optional category filter
            status: Optional status filter
            limit: Maximum results

        Returns:
            List of pipeline definition info
        """
        stmt = (
            select(Resource, PipelineDefinition)
            .join(PipelineDefinition, Resource.id == PipelineDefinition.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "PipelineDef",
            )
        )

        if category:
            stmt = stmt.where(PipelineDefinition.category == category)

        if status:
            stmt = stmt.where(Resource.status == status)

        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(resource.id),
                "name": resource.name,
                "code_ref": definition.code_ref,
                "category": definition.category,
                "status": resource.status,
            }
            for resource, definition in rows
        ]

    async def list_instances(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        parent_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List pipeline instances.

        Args:
            session: Database session
            actor: Actor context
            parent_id: Optional parent filter
            status: Optional status filter
            limit: Maximum results

        Returns:
            List of pipeline instance info
        """
        stmt = (
            select(Resource, PipelineInstance)
            .join(PipelineInstance, Resource.id == PipelineInstance.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "PipelineInstance",
                Resource.status == "active",
            )
        )

        if parent_id:
            stmt = stmt.where(Resource.parent_id == parent_id)

        if status:
            stmt = stmt.where(PipelineInstance.status == status)

        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(resource.id),
                "name": resource.name,
                "definition_id": str(instance.definition_resource_id),
                "status": instance.status,
                "last_run_at": instance.last_run_at.isoformat()
                if instance.last_run_at
                else None,
            }
            for resource, instance in rows
        ]
