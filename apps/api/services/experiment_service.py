"""Experiment Service - Expression Experiment Management.

This service handles:
- Creating expression experiments
- Running experiments (previewing expressions)
- Saving experiments as macros
- Managing experiment history

Experiments allow users to:
1. Write expressions using operators (MEAN, DELTA, CORR, etc.)
2. Preview results against datasets
3. Save successful expressions as reusable macros
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox, tx_activity
from libs.core.rbac.models import ActorContext
from libs.data.expression import ExpressionEngine
from libs.db.models.quant import (
    ExperimentInstance,
    OpMacroDefinition,
)
from libs.db.models.resource import Resource

if TYPE_CHECKING:
    import pandas as pd


class ExperimentService:
    """Service for expression experiment operations.

    Experiments are the research layer:
    - Create: Define expression + input dataset references
    - Run: Evaluate expression and preview results
    - Save: Promote to OpMacroDef for reuse
    """

    def __init__(self) -> None:
        """Initialize service."""
        self.expression_engine = ExpressionEngine()

    async def create_experiment(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        name: str,
        expression: str,
        parent_id: UUID,
        input_datasets: dict[str, UUID] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new expression experiment.

        Args:
            session: Database session
            actor: Actor context
            name: Experiment name
            expression: Expression to evaluate
            parent_id: Parent resource (Project)
            input_datasets: Map of alias to dataset UUIDs
            description: Optional description

        Returns:
            Experiment info
        """
        # Parse expression to extract metadata (validation happens on evaluate)
        try:
            datasets_referenced = self.expression_engine.validate_expression(expression)
            operators_used = self.expression_engine.get_used_operators(expression)
        except Exception as e:
            raise ValueError(f"Invalid expression syntax: {e}")

        resource_id = uuid4()

        async def domain_fn(sess: AsyncSession) -> Resource:
            # Create Resource
            resource = Resource(
                id=resource_id,
                tenant_id=actor.tenant_id,
                type="ExperimentInstance",
                parent_id=parent_id,
                owner_principal_id=actor.id,
                name=name,
                space_kind="personal",
                subspace_kind="staging",
                status="active",
                metadata_json={"description": description} if description else {},
            )
            sess.add(resource)

            # Create Extension
            instance = ExperimentInstance(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                expression_text=expression,
                input_datasets_json={k: str(v) for k, v in (input_datasets or {}).items()},
            )
            sess.add(instance)
            await sess.flush()
            return resource

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type="ExperimentInstance",
            action="experiment.created",
            payload={
                "name": name,
                "expression": expression,
                "operators_used": operators_used,
            },
        )
        resource, _ = await tx_activity(session, envelope, domain_fn)

        return {
            "id": str(resource_id),
            "name": name,
            "expression": expression,
            "operators_used": operators_used,
            "datasets_referenced": datasets_referenced,
            "status": "created",
        }

    async def run_experiment(
        self,
        session: AsyncSession,
        actor: ActorContext,
        experiment_id: UUID,
        context: dict[str, "pd.DataFrame | pd.Series"],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Run an experiment and return preview results.

        Args:
            session: Database session
            actor: Actor context
            experiment_id: Experiment to run
            context: Dict mapping dataset aliases to DataFrames
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit: Maximum rows to return

        Returns:
            Experiment run results
        """
        instance = await session.get(ExperimentInstance, experiment_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"ExperimentInstance {experiment_id} not found")

        resource = await session.get(Resource, experiment_id)

        # Evaluate expression
        try:
            result = self.expression_engine.evaluate(instance.expression_text, context)
        except Exception as e:
            # Emit failure activity
            envelope = ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=experiment_id,
                resource_type="ExperimentInstance",
                action="experiment.run_failed",
                payload={
                    "error": str(e),
                    "expression": instance.expression_text,
                },
            )
            await record_activity_with_outbox(session, envelope)
            await session.commit()

            return {
                "id": str(experiment_id),
                "success": False,
                "error": str(e),
            }

        # Emit success activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=experiment_id,
            resource_type="ExperimentInstance",
            action="experiment.run_completed",
            payload={
                "expression": instance.expression_text,
                "result_rows": len(result) if hasattr(result, "__len__") else 1,
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        # Convert result to response
        return self._result_to_response(result, resource.name, instance.expression_text, limit)

    async def save_as_macro(
        self,
        session: AsyncSession,
        actor: ActorContext,
        experiment_id: UUID,
        *,
        macro_name: str | None = None,
    ) -> dict[str, Any]:
        """Save an experiment as a reusable macro.

        Creates an OpMacroDef resource from the experiment.

        Args:
            session: Database session
            actor: Actor context
            experiment_id: Experiment to save
            macro_name: Optional override for macro name

        Returns:
            Macro info
        """
        instance = await session.get(ExperimentInstance, experiment_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"ExperimentInstance {experiment_id} not found")

        resource = await session.get(Resource, experiment_id)
        name = macro_name or f"Macro_{resource.name}"

        macro_id = uuid4()

        async def domain_fn(sess: AsyncSession) -> Resource:
            # Create Resource for macro
            macro_resource = Resource(
                id=macro_id,
                tenant_id=actor.tenant_id,
                type="OpMacroDef",
                parent_id=resource.parent_id,
                owner_principal_id=actor.id,
                name=name,
                space_kind="team",
                subspace_kind="staging",
                status="active",
                metadata_json={"source_experiment_id": str(experiment_id)},
            )
            sess.add(macro_resource)

            # Create Extension
            macro_def = OpMacroDefinition(
                resource_id=macro_id,
                tenant_id=actor.tenant_id,
                expression_text=instance.expression_text,
                input_aliases=list(instance.input_datasets_json.keys()),
            )
            sess.add(macro_def)
            await sess.flush()
            return macro_resource

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=macro_id,
            resource_type="OpMacroDef",
            action="macro.saved",
            payload={
                "name": name,
                "source_experiment_id": str(experiment_id),
                "expression": instance.expression_text,
            },
        )
        _, _ = await tx_activity(session, envelope, domain_fn)

        return {
            "id": str(macro_id),
            "name": name,
            "expression": instance.expression_text,
            "input_aliases": list(instance.input_datasets_json.keys()),
            "status": "saved",
        }

    async def get_experiment(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        experiment_id: UUID,
    ) -> dict[str, Any] | None:
        """Get experiment details.

        Args:
            session: Database session
            tenant_id: Tenant ID
            experiment_id: Experiment resource ID

        Returns:
            Experiment info or None
        """
        instance = await session.get(ExperimentInstance, experiment_id)
        if not instance or instance.tenant_id != tenant_id:
            return None

        resource = await session.get(Resource, experiment_id)
        if not resource:
            return None

        # Extract expression metadata
        try:
            datasets_referenced = self.expression_engine.validate_expression(instance.expression_text)
            operators_used = self.expression_engine.get_used_operators(instance.expression_text)
        except Exception:
            datasets_referenced = []
            operators_used = []

        return {
            "id": str(experiment_id),
            "name": resource.name,
            "expression": instance.expression_text,
            "input_datasets": instance.input_datasets_json,
            "operators_used": operators_used,
            "datasets_referenced": datasets_referenced,
            "created_at": resource.created_at.isoformat(),
        }

    async def list_experiments(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        parent_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List experiments.

        Args:
            session: Database session
            actor: Actor context
            parent_id: Optional parent filter
            limit: Maximum results

        Returns:
            List of experiment info
        """
        stmt = (
            select(Resource, ExperimentInstance)
            .join(ExperimentInstance, Resource.id == ExperimentInstance.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "ExperimentInstance",
                Resource.status == "active",
            )
        )

        if parent_id:
            stmt = stmt.where(Resource.parent_id == parent_id)

        stmt = stmt.order_by(Resource.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(resource.id),
                "name": resource.name,
                "expression": instance.expression_text[:100] + "..." if len(instance.expression_text) > 100 else instance.expression_text,
                "created_at": resource.created_at.isoformat(),
            }
            for resource, instance in rows
        ]

    async def update_experiment(
        self,
        session: AsyncSession,
        actor: ActorContext,
        experiment_id: UUID,
        *,
        expression: str | None = None,
        input_datasets: dict[str, UUID] | None = None,
    ) -> dict[str, Any]:
        """Update an experiment.

        Args:
            session: Database session
            actor: Actor context
            experiment_id: Experiment to update
            expression: New expression
            input_datasets: New input datasets

        Returns:
            Updated experiment info
        """
        instance = await session.get(ExperimentInstance, experiment_id)
        if not instance or instance.tenant_id != actor.tenant_id:
            raise ValueError(f"ExperimentInstance {experiment_id} not found")

        resource = await session.get(Resource, experiment_id)
        changes = {}

        if expression is not None:
            # Parse new expression to validate syntax
            try:
                self.expression_engine.validate_expression(expression)
                self.expression_engine.get_used_operators(expression)
            except Exception as e:
                raise ValueError(f"Invalid expression syntax: {e}")

            changes["expression"] = {"old": instance.expression_text, "new": expression}
            instance.expression_text = expression

        if input_datasets is not None:
            changes["input_datasets"] = {
                "old": instance.input_datasets_json,
                "new": {k: str(v) for k, v in input_datasets.items()},
            }
            instance.input_datasets_json = {k: str(v) for k, v in input_datasets.items()}

        if changes:
            await session.flush()

            # Emit activity
            envelope = ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=experiment_id,
                resource_type="ExperimentInstance",
                action="experiment.updated",
                payload={"changes": changes},
            )
            await record_activity_with_outbox(session, envelope)
            await session.commit()

        return {
            "id": str(experiment_id),
            "name": resource.name,
            "expression": instance.expression_text,
            "input_datasets": instance.input_datasets_json,
            "status": "updated",
        }

    def _result_to_response(
        self,
        result: Any,
        name: str,
        expression: str,
        limit: int,
    ) -> dict[str, Any]:
        """Convert evaluation result to API response.

        Args:
            result: Evaluation result
            name: Experiment name
            expression: Expression text
            limit: Max rows

        Returns:
            Response dict
        """
        import pandas as pd

        if isinstance(result, pd.DataFrame):
            # Handle DatetimeIndex
            if isinstance(result.index, pd.DatetimeIndex):
                result = result.reset_index()
                result.columns = ["date"] + list(result.columns[1:])

            records = result.head(limit).to_dict(orient="records")
            # Convert timestamps
            for record in records:
                for key, value in record.items():
                    if isinstance(value, (pd.Timestamp, date)):
                        record[key] = str(value)

            return {
                "success": True,
                "name": name,
                "expression": expression,
                "result_type": "dataframe",
                "columns": list(result.columns),
                "data": records,
                "row_count": len(result),
                "truncated": len(result) > limit,
            }

        elif isinstance(result, pd.Series):
            df = result.to_frame("value").reset_index()
            records = df.head(limit).to_dict(orient="records")
            for record in records:
                for key, value in record.items():
                    if isinstance(value, (pd.Timestamp, date)):
                        record[key] = str(value)

            return {
                "success": True,
                "name": name,
                "expression": expression,
                "result_type": "series",
                "columns": list(df.columns),
                "data": records,
                "row_count": len(result),
                "truncated": len(result) > limit,
            }

        else:
            # Scalar result
            return {
                "success": True,
                "name": name,
                "expression": expression,
                "result_type": "scalar",
                "value": result,
            }
