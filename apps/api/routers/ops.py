"""Operators API Router.

Provides endpoints for:
- Listing available operators
- Getting operator details
- Evaluating expressions
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_actor, get_db
from apps.api.schemas import (
    ExpressionEvaluateOut,
    ExpressionEvaluateRequest,
    OperatorListOut,
    OperatorOut,
)
from apps.api.services import OpService
from libs.core.rbac.models import ActorContext

router = APIRouter(prefix="/ops", tags=["Operators"])


@router.get("", response_model=OperatorListOut)
async def list_operators(
    category: Optional[str] = Query(default=None, examples=["rolling"]),
) -> OperatorListOut:
    """List available operators.

    Args:
        category: Optional filter by category (rolling, time_series, cross_section, etc.)

    Returns:
        List of operator info
    """
    service = OpService()
    operators = service.list_operators(category=category)

    return OperatorListOut(
        operators=[
            OperatorOut(
                name=op["name"],
                category=op["category"],
                arity=op["arity"],
                description=op["description"],
            )
            for op in operators
        ],
        count=len(operators),
    )


@router.get("/{name}", response_model=OperatorOut)
async def get_operator(name: str) -> OperatorOut:
    """Get operator details.

    Args:
        name: Operator name (e.g., MEAN, DELTA, CORR)

    Returns:
        Operator info or 404
    """
    service = OpService()
    op = service.get_operator(name)

    if not op:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Operator '{name}' not found")

    return OperatorOut(
        name=op["name"],
        category=op["category"],
        arity=op["arity"],
        description=op["description"],
    )


@router.post("/evaluate", response_model=ExpressionEvaluateOut)
async def evaluate_expression(
    payload: ExpressionEvaluateRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ExpressionEvaluateOut:
    """Evaluate an expression.

    The expression can reference datasets using $alias syntax.
    Context maps aliases to dataset resource IDs.

    Args:
        payload: Expression and context
        actor: Actor context
        db: Database session

    Returns:
        Evaluation result or errors
    """
    service = OpService()

    # TODO: Load actual DataFrames from dataset resources
    # For now, evaluate with empty context (expression validation only)
    result = await service.evaluate_expression(
        session=db,
        actor=actor,
        expression=payload.expression,
        context={},  # Would load DataFrames from payload.context UUIDs
    )

    return ExpressionEvaluateOut(
        success=result.get("success", False),
        expression=result.get("expression", payload.expression),
        result_type=result.get("result_type"),
        columns=result.get("columns"),
        data=result.get("data"),
        value=result.get("value"),
        row_count=result.get("row_count"),
        truncated=result.get("truncated"),
        errors=result.get("errors"),
    )
