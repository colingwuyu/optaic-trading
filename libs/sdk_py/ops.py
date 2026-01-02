"""Operators SDK client.

Provides methods for:
- Listing available operators
- Getting operator details
- Evaluating expressions
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID

if TYPE_CHECKING:
    from .client import AsyncPlatformClient


def _to_str(value: Optional[str | UUID]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


class OpsClient:
    """Client for operator operations."""

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def list(
        self,
        *,
        category: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """List all available operators.

        Args:
            category: Optional category filter (e.g., "rolling", "time_series")
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Dict with "operators" list and "count"
        """
        params = _drop_none({"category": category})
        return await self._client._request(
            "GET",
            "/ops",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params if params else None,
        )

    async def get(
        self,
        name: str,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get details for a specific operator.

        Args:
            name: Operator name (e.g., "MEAN", "REF", "DELTA")
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Operator details with name, category, arity, description
        """
        return await self._client._request(
            "GET",
            f"/ops/{name}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def evaluate(
        self,
        expression: str,
        context: Dict[str, str | UUID],
        *,
        start_date: Optional[date | str] = None,
        end_date: Optional[date | str] = None,
        limit: int = 100,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Evaluate an expression with dataset context.

        Args:
            expression: Expression string (e.g., "MEAN($close, 20)")
            context: Map of variable names to dataset resource IDs
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit: Maximum rows to return (default 100)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Evaluation result with columns, data, row_count, truncated
        """
        # Convert context values to strings
        context_str = {k: str(v) for k, v in context.items()}

        # Convert dates to ISO format strings
        start_str = None
        if start_date:
            start_str = (
                start_date.isoformat()
                if isinstance(start_date, date)
                else start_date
            )
        end_str = None
        if end_date:
            end_str = (
                end_date.isoformat() if isinstance(end_date, date) else end_date
            )

        payload = _drop_none(
            {
                "expression": expression,
                "context": context_str,
                "start_date": start_str,
                "end_date": end_str,
                "limit": limit,
            }
        )
        return await self._client._request(
            "POST",
            "/ops/evaluate",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )
