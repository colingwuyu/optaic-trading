"""Datasets SDK client.

Provides methods for:
- Listing datasets
- Getting dataset info and status
- Previewing dataset data (PIT-aware)
- Triggering dataset refresh
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


class DatasetsClient:
    """Client for dataset operations."""

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def create(
        self,
        name: str,
        parent_id: str | UUID,
        pipeline_instance_id: str | UUID,
        store_instance_id: str | UUID,
        accessor_instance_id: str | UUID,
        *,
        freshness_status: str = "unknown",
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a new dataset instance.

        A DatasetInstance combines:
        - A PipelineInstance (data source/transformation)
        - A StoreInstance (where data is stored)
        - An AccessorInstance (how data is retrieved)

        Args:
            name: Dataset name
            parent_id: Parent resource ID (typically a Project)
            pipeline_instance_id: Reference to pipeline instance
            store_instance_id: Reference to store instance
            accessor_instance_id: Reference to accessor instance
            freshness_status: Initial freshness status (default "unknown")
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Created dataset info with id, name, type, status, component IDs
        """
        payload = {
            "name": name,
            "parent_id": str(parent_id),
            "pipeline_instance_id": str(pipeline_instance_id),
            "store_instance_id": str(store_instance_id),
            "accessor_instance_id": str(accessor_instance_id),
            "freshness_status": freshness_status,
        }
        return await self._client._request(
            "POST",
            "/datasets",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def list(
        self,
        *,
        parent_id: Optional[str | UUID] = None,
        freshness_status: Optional[str] = None,
        limit: int = 50,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        """List datasets.

        Args:
            parent_id: Optional parent resource filter
            freshness_status: Optional freshness filter ("fresh", "stale")
            limit: Maximum results (default 50, max 200)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            List of dataset info dicts
        """
        params = _drop_none(
            {
                "parent_id": _to_str(parent_id),
                "freshness_status": freshness_status,
                "limit": limit,
            }
        )
        return await self._client._request(
            "GET",
            "/datasets",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def get(
        self,
        dataset_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get dataset info.

        Args:
            dataset_id: Dataset resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Dataset info with id, name, freshness_status, last_data_date, row_count
        """
        return await self._client._request(
            "GET",
            f"/datasets/{dataset_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def status(
        self,
        dataset_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get dataset freshness status.

        Args:
            dataset_id: Dataset resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Dataset status info
        """
        return await self._client._request(
            "GET",
            f"/datasets/{dataset_id}/status",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def preview(
        self,
        dataset_id: str | UUID,
        *,
        start_date: Optional[date | str] = None,
        end_date: Optional[date | str] = None,
        as_of_date: Optional[date | str] = None,
        limit: int = 100,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Preview dataset data.

        Supports PIT (point-in-time) queries via as_of_date parameter.

        Args:
            dataset_id: Dataset resource ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            as_of_date: Optional PIT date (see data as of this date)
            limit: Maximum rows to return (default 100)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Dataset preview with columns, data, row_count, truncated
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
                "as_of_date": _date_str(as_of_date),
                "limit": limit,
            }
        )
        return await self._client._request(
            "POST",
            f"/datasets/{dataset_id}/preview",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def refresh(
        self,
        dataset_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Trigger dataset refresh.

        Queues the dataset for refresh by running its associated pipeline.

        Args:
            dataset_id: Dataset resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Refresh status with id, name, status, message
        """
        return await self._client._request(
            "POST",
            f"/datasets/{dataset_id}/refresh",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )
