"""Experiments SDK client.

Provides methods for:
- Creating expression experiments
- Running experiments (previewing expressions)
- Updating experiments
- Saving experiments as macros
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


class ExperimentsClient:
    """Client for experiment operations."""

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def list(
        self,
        *,
        parent_id: Optional[str | UUID] = None,
        limit: int = 50,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        """List experiments.

        Args:
            parent_id: Optional parent resource filter
            limit: Maximum results (default 50, max 200)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            List of experiment info dicts
        """
        params = _drop_none(
            {
                "parent_id": _to_str(parent_id),
                "limit": limit,
            }
        )
        return await self._client._request(
            "GET",
            "/experiments",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def create(
        self,
        name: str,
        expression: str,
        parent_id: str | UUID,
        *,
        input_datasets: Optional[Dict[str, str | UUID]] = None,
        description: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a new expression experiment.

        Experiments allow writing and testing expressions before
        saving them as reusable macros.

        Args:
            name: Experiment name
            expression: Expression string (e.g., "MEAN($close, 20)")
            parent_id: Parent resource ID (typically a Project)
            input_datasets: Map of variable names to dataset resource IDs
            description: Optional description
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Created experiment info
        """
        # Convert input_datasets values to strings
        input_ds = None
        if input_datasets:
            input_ds = {k: str(v) for k, v in input_datasets.items()}

        payload = _drop_none(
            {
                "name": name,
                "expression": expression,
                "parent_id": str(parent_id),
                "input_datasets": input_ds,
                "description": description,
            }
        )
        return await self._client._request(
            "POST",
            "/experiments",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def get(
        self,
        experiment_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get experiment details.

        Args:
            experiment_id: Experiment resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Experiment info with id, name, expression, operators_used, datasets_referenced
        """
        return await self._client._request(
            "GET",
            f"/experiments/{experiment_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def run(
        self,
        experiment_id: str | UUID,
        *,
        start_date: Optional[date | str] = None,
        end_date: Optional[date | str] = None,
        limit: int = 100,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Run an experiment and return preview results.

        Args:
            experiment_id: Experiment resource ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit: Maximum rows to return (default 100)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Experiment run results with success, columns, data, row_count
        """

        # Convert dates to ISO format strings
        def _date_str(d: Optional[date | str]) -> Optional[str]:
            if d is None:
                return None
            return d.isoformat() if isinstance(d, date) else d

        payload = _drop_none(
            {
                "start_date": _date_str(start_date),
                "end_date": _date_str(end_date),
                "limit": limit,
            }
        )
        return await self._client._request(
            "POST",
            f"/experiments/{experiment_id}/run",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def update(
        self,
        experiment_id: str | UUID,
        *,
        expression: Optional[str] = None,
        input_datasets: Optional[Dict[str, str | UUID]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Update an experiment.

        Args:
            experiment_id: Experiment resource ID
            expression: New expression string
            input_datasets: New input dataset mappings
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Updated experiment info
        """
        # Convert input_datasets values to strings
        input_ds = None
        if input_datasets is not None:
            input_ds = {k: str(v) for k, v in input_datasets.items()}

        payload = _drop_none(
            {
                "expression": expression,
                "input_datasets": input_ds,
            }
        )

        if not payload:
            raise ValueError("At least one field must be provided for update")

        return await self._client._request(
            "PATCH",
            f"/experiments/{experiment_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def save_as_macro(
        self,
        experiment_id: str | UUID,
        *,
        macro_name: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Save an experiment as a reusable macro.

        Creates an OpMacroDef resource from the experiment.

        Args:
            experiment_id: Experiment resource ID
            macro_name: Optional override for macro name
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Macro info with id, name, expression, input_aliases, status
        """
        params = _drop_none({"macro_name": macro_name})
        return await self._client._request(
            "POST",
            f"/experiments/{experiment_id}/save-as-macro",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params if params else None,
        )
