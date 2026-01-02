"""Pipelines SDK client.

Provides methods for:
- Submitting and deploying pipeline definitions
- Creating and managing pipeline instances
- Triggering pipeline runs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

if TYPE_CHECKING:
    from .client import AsyncPlatformClient


def _to_str(value: Optional[str | UUID]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


class PipelinesClient:
    """Client for pipeline operations."""

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    # --- Definition Methods ---

    async def submit_definition(
        self,
        name: str,
        code_ref: str,
        parent_id: str | UUID,
        *,
        category: str = "etl",
        interface_spec: Optional[str] = None,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        parameters_schema: Optional[Dict[str, Any]] = None,
        guardrail_contracts: Optional[List[Dict[str, Any]]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Submit a new pipeline definition.

        Creates a PipelineDefinition resource in draft status.
        Must be deployed before it can be used to create instances.

        Args:
            name: Definition name
            code_ref: Code reference for the pipeline implementation
            parent_id: Parent resource ID (typically a Space)
            category: Definition category (default "etl")
            interface_spec: Interface specification for the pipeline
            input_schema: Input schema JSON
            output_schema: Output schema JSON
            parameters_schema: Parameters schema JSON
            guardrail_contracts: List of guardrail contract definitions
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Created definition info with id, name, code_ref, category, status
        """
        payload = _drop_none(
            {
                "name": name,
                "code_ref": code_ref,
                "category": category,
                "parent_id": str(parent_id),
                "interface_spec": interface_spec,
                "input_schema": input_schema or {},
                "output_schema": output_schema or {},
                "parameters_schema": parameters_schema or {},
                "guardrail_contracts": guardrail_contracts or [],
            }
        )
        return await self._client._request(
            "POST",
            "/pipelines/definitions",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def deploy_definition(
        self,
        definition_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Deploy a pipeline definition.

        Changes status from draft to active, allowing instance creation.

        Args:
            definition_id: Pipeline definition resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Deployed definition info
        """
        return await self._client._request(
            "POST",
            f"/pipelines/definitions/{definition_id}/deploy",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def list_definitions(
        self,
        *,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        """List pipeline definitions.

        Args:
            category: Optional category filter
            status: Optional status filter ("draft", "active")
            limit: Maximum results (default 50, max 200)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            List of definition info dicts
        """
        params = _drop_none(
            {
                "category": category,
                "status": status,
                "limit": limit,
            }
        )
        return await self._client._request(
            "GET",
            "/pipelines/definitions",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    # --- Instance Methods ---

    async def create_instance(
        self,
        name: str,
        definition_id: str | UUID,
        parent_id: str | UUID,
        *,
        config: Optional[Dict[str, Any]] = None,
        schedule: Optional[Dict[str, Any]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a pipeline instance from a definition.

        Args:
            name: Instance name
            definition_id: Pipeline definition resource ID
            parent_id: Parent resource ID (typically a Project)
            config: Pipeline configuration parameters
            schedule: Schedule configuration (e.g., {"cron": "0 6 * * *"})
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Created instance info with id, name, definition_id, code_ref, status
        """
        payload = _drop_none(
            {
                "name": name,
                "definition_id": str(definition_id),
                "parent_id": str(parent_id),
                "config": config or {},
                "schedule": schedule,
            }
        )
        return await self._client._request(
            "POST",
            "/pipelines/instances",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def run(
        self,
        instance_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Trigger a pipeline run.

        Args:
            instance_id: Pipeline instance resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Run submission info with instance_id, code_ref, status, message
        """
        return await self._client._request(
            "POST",
            f"/pipelines/instances/{instance_id}/run",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def list_instances(
        self,
        *,
        parent_id: Optional[str | UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        """List pipeline instances.

        Args:
            parent_id: Optional parent resource filter
            status: Optional status filter ("idle", "running")
            limit: Maximum results (default 50, max 200)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            List of instance info dicts
        """
        params = _drop_none(
            {
                "parent_id": _to_str(parent_id),
                "status": status,
                "limit": limit,
            }
        )
        return await self._client._request(
            "GET",
            "/pipelines/instances",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )
