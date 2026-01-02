"""Signals SDK client.

Provides methods for:
- Registering datasets as signals
- Getting signal specs
- Validating signals
- Promoting signals to official status
"""

from __future__ import annotations

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


class SignalsClient:
    """Client for signal operations."""

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def list(
        self,
        *,
        parent_id: Optional[str | UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        """List signals.

        Args:
            parent_id: Optional parent resource filter
            status: Optional status filter ("staging", "official")
            limit: Maximum results (default 50, max 200)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            List of signal info dicts
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
            "/signals",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def register(
        self,
        dataset_id: str | UUID,
        name: str,
        *,
        parent_id: Optional[str | UUID] = None,
        min_value: float = -1.0,
        max_value: float = 1.0,
        allow_nan: bool = False,
        neutral_value: float = 0.0,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Register a dataset as a signal.

        Args:
            dataset_id: Source dataset resource ID
            name: Signal name
            parent_id: Optional parent resource ID
            min_value: Minimum allowed value (default -1.0)
            max_value: Maximum allowed value (default 1.0)
            allow_nan: Whether NaN values are allowed (default False)
            neutral_value: Neutral/default value (default 0.0)
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Signal info with id, name, spec, status
        """
        payload = _drop_none(
            {
                "dataset_id": str(dataset_id),
                "name": name,
                "parent_id": _to_str(parent_id),
                "min_value": min_value,
                "max_value": max_value,
                "allow_nan": allow_nan,
                "neutral_value": neutral_value,
            }
        )
        return await self._client._request(
            "POST",
            "/signals",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def get(
        self,
        signal_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get signal info.

        Args:
            signal_id: Signal resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Signal info with id, name, spec, status
        """
        return await self._client._request(
            "GET",
            f"/signals/{signal_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def validate(
        self,
        signal_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Validate a signal against its spec.

        Args:
            signal_id: Signal resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Validation result with id, valid, issues
        """
        return await self._client._request(
            "POST",
            f"/signals/{signal_id}/validate",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def promote(
        self,
        signal_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Promote a signal from staging to official status.

        Args:
            signal_id: Signal resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Updated signal info with new status
        """
        return await self._client._request(
            "POST",
            f"/signals/{signal_id}/promote",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )
