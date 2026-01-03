"""Operator Service - Expression Evaluation.

This service handles:
- Listing available operators
- Evaluating expressions
- Managing operator macros (saved expressions)

The OPS_REGISTRY contains all registered operators that can be used in expressions.
OpDefinition resources reference these operators via code_ref.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.core.rbac.models import ActorContext
from libs.data.expression import ExpressionEngine
from libs.data.ops import OPS_REGISTRY
from libs.db.models.quant import OpDefinition, OpMacroDefinition
from libs.db.models.resource import Resource

if TYPE_CHECKING:
    import pandas as pd


class OpService:
    """Service for operator and expression operations.

    This service provides:
    - List of available operators from OPS_REGISTRY
    - Expression evaluation with dataset context
    - Operator metadata from OpDefinition resources
    """

    def __init__(self) -> None:
        """Initialize service."""
        self.expression_engine = ExpressionEngine()

    def list_operators(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all available operators.

        Returns operators directly from OPS_REGISTRY.
        For full metadata (description, schemas), query OpDefinition resources.

        Args:
            category: Optional filter by category

        Returns:
            List of operator info dicts
        """
        import inspect

        operators = []
        for name, func in OPS_REGISTRY.items():
            op_category = getattr(func, "category", "Other")

            # Apply category filter if provided
            if category and op_category.lower() != category.lower():
                continue

            # Get arity from function signature
            try:
                sig = inspect.signature(func)
                arity = len(sig.parameters)
            except (ValueError, TypeError):
                arity = 0

            # Get description from docstring
            description = (func.__doc__ or "").split("\n")[0].strip()

            operators.append(
                {
                    "name": name,
                    "category": op_category,
                    "code_ref": name,  # code_ref matches registry key
                    "arity": arity,
                    "description": description,
                }
            )
        return sorted(operators, key=lambda x: (x["category"], x["name"]))

    async def list_operators_with_metadata(
        self,
        session: AsyncSession,
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """List operators with full metadata from OpDefinition resources.

        This queries the database for OpDefinition resources which contain
        additional metadata like signature, input/output schemas, etc.

        Args:
            session: Database session
            tenant_id: Tenant ID

        Returns:
            List of operator info with full metadata
        """
        stmt = (
            select(Resource, OpDefinition)
            .join(OpDefinition, Resource.id == OpDefinition.resource_id)
            .where(
                Resource.tenant_id == tenant_id,
                Resource.type == "OpDef",
                Resource.status == "active",
            )
        )

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(resource.id),
                "name": resource.name,
                "code_ref": op_def.code_ref,
                "category": op_def.category,
                "signature": op_def.signature,
                "input_schema": op_def.input_schema,
                "output_schema": op_def.output_schema,
            }
            for resource, op_def in rows
        ]

    def get_operator(self, name: str) -> dict[str, Any] | None:
        """Get operator by name.

        Args:
            name: Operator name (case-insensitive)

        Returns:
            Operator info or None if not found
        """
        import inspect

        key = name.upper()
        func = OPS_REGISTRY.get(key)
        if not func:
            return None

        # Get arity from function signature
        try:
            sig = inspect.signature(func)
            arity = len(sig.parameters)
        except (ValueError, TypeError):
            arity = 0

        # Get description from docstring
        description = (func.__doc__ or "").split("\n")[0].strip()

        return {
            "name": key,
            "category": getattr(func, "category", "Other"),
            "code_ref": key,
            "arity": arity,
            "description": description,
        }

    async def evaluate_expression(
        self,
        session: AsyncSession,
        actor: ActorContext,
        expression: str,
        context: dict[str, "pd.DataFrame | pd.Series"],
        *,
        emit_activity: bool = True,
    ) -> dict[str, Any]:
        """Evaluate an expression with given context.

        Args:
            session: Database session
            actor: Actor context
            expression: Expression string (e.g., "MEAN($price, 20)")
            context: Dict mapping dataset aliases to DataFrames
            emit_activity: Whether to emit activity for audit

        Returns:
            Evaluation result with data and metadata
        """

        # Extract expression metadata (actual validation happens during evaluate)
        try:
            datasets_used = self.expression_engine.validate_expression(expression)
            operators_used = self.expression_engine.get_used_operators(expression)
        except Exception as e:
            return {
                "success": False,
                "errors": [f"Invalid expression syntax: {e}"],
            }

        # Evaluate
        try:
            result = self.expression_engine.evaluate(expression, context)
        except Exception as e:
            return {
                "success": False,
                "errors": [str(e)],
            }

        # Emit activity
        if emit_activity:
            envelope = ActivityEnvelope(
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource_id=actor.id,  # Use actor as resource for expressions
                resource_type="Expression",
                action="expression.evaluated",
                payload={
                    "expression": expression,
                    "datasets_used": datasets_used,
                    "operators_used": operators_used,
                },
            )
            await record_activity_with_outbox(session, envelope)
            await session.commit()

        # Convert result to response
        return self._result_to_response(
            result, expression, datasets_used, operators_used
        )

    async def list_macros(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        parent_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """List saved expression macros.

        Args:
            session: Database session
            tenant_id: Tenant ID
            parent_id: Optional parent resource filter

        Returns:
            List of macro info dicts
        """
        stmt = (
            select(Resource, OpMacroDefinition)
            .join(OpMacroDefinition, Resource.id == OpMacroDefinition.resource_id)
            .where(
                Resource.tenant_id == tenant_id,
                Resource.type == "OpMacroDef",
                Resource.status == "active",
            )
        )

        if parent_id:
            stmt = stmt.where(Resource.parent_id == parent_id)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "id": str(resource.id),
                "name": resource.name,
                "expression": macro_def.expression_text,
                "input_aliases": macro_def.input_aliases,
            }
            for resource, macro_def in rows
        ]

    def _result_to_response(
        self,
        result: Any,
        expression: str,
        datasets_used: list[str],
        operators_used: list[str],
    ) -> dict[str, Any]:
        """Convert evaluation result to API response.

        Args:
            result: Evaluation result (DataFrame, Series, or scalar)
            expression: Original expression
            datasets_used: List of dataset references in expression
            operators_used: List of operators used in expression

        Returns:
            Response dict
        """
        import pandas as pd

        if isinstance(result, pd.DataFrame):
            # Handle DatetimeIndex
            if isinstance(result.index, pd.DatetimeIndex):
                result = result.reset_index()
                result.columns = ["date"] + list(result.columns[1:])

            records = result.head(1000).to_dict(orient="records")
            # Convert timestamps
            for record in records:
                for key, value in record.items():
                    if isinstance(value, (pd.Timestamp, date)):
                        record[key] = str(value)

            return {
                "success": True,
                "expression": expression,
                "result_type": "dataframe",
                "columns": list(result.columns),
                "data": records,
                "row_count": len(result),
                "truncated": len(result) > 1000,
                "datasets_used": datasets_used,
                "operators_used": operators_used,
            }

        elif isinstance(result, pd.Series):
            # Handle DatetimeIndex
            if isinstance(result.index, pd.DatetimeIndex):
                df = result.reset_index()
                df.columns = ["date", "value"]
            else:
                df = result.to_frame("value").reset_index()

            records = df.head(1000).to_dict(orient="records")
            for record in records:
                for key, value in record.items():
                    if isinstance(value, (pd.Timestamp, date)):
                        record[key] = str(value)

            return {
                "success": True,
                "expression": expression,
                "result_type": "series",
                "columns": list(df.columns),
                "data": records,
                "row_count": len(result),
                "truncated": len(result) > 1000,
                "datasets_used": datasets_used,
                "operators_used": operators_used,
            }

        else:
            # Scalar result
            return {
                "success": True,
                "expression": expression,
                "result_type": "scalar",
                "value": result,
                "datasets_used": datasets_used,
                "operators_used": operators_used,
            }
