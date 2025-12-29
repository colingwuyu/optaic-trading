from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

import httpx

def _to_str(value: Optional[str | UUID]) -> Optional[str]:
    if value is None:
        return None
    return str(value)

def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}

class AsyncPlatformClient:
    def __init__(
        self,
        base_url: str,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._principal_id = _to_str(principal_id)
        self._tenant_id = _to_str(tenant_id)
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout
        )
        self.health = HealthClient(self)
        self.tenants = TenantsClient(self)
        self.principals = PrincipalsClient(self)
        self.resources = ResourcesClient(self)
        self.refs = RefsClient(self)
        self.merge_requests = MergeRequestsClient(self)
        self.promotions = PromotionsClient(self)
        self.rbac = RbacClient(self)
        self.activities = ActivitiesClient(self)
        self.chat = ChatClient(self)

    async def __aenter__(self) -> "AsyncPlatformClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def set_principal_id(self, principal_id: Optional[str | UUID]) -> None:
        self._principal_id = _to_str(principal_id)

    def set_tenant_id(self, tenant_id: Optional[str | UUID]) -> None:
        self._tenant_id = _to_str(tenant_id)

    def _headers(
        self,
        principal_id: Optional[str | UUID],
        tenant_id: Optional[str | UUID],
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        resolved_principal = _to_str(principal_id) or self._principal_id
        if resolved_principal:
            headers["X-Principal-Id"] = resolved_principal
        resolved_tenant = _to_str(tenant_id) or self._tenant_id
        if resolved_tenant:
            headers["X-Tenant-Id"] = resolved_tenant
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        response = await self._client.request(
            method,
            path,
            headers=self._headers(principal_id, tenant_id, headers),
            params=params,
            json=json,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

class HealthClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def get(self) -> Dict[str, Any]:
        return await self._client._request("GET", "/healthz")

class TenantsClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create(
        self,
        name: str,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {"name": name}
        return await self._client._request(
            "POST",
            "/tenants",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def list(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        return await self._client._request(
            "GET", "/tenants", principal_id=principal_id, tenant_id=tenant_id
        )

class PrincipalsClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create(
        self,
        display_name: str,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
        principal_uuid: Optional[str | UUID] = None,
        kind: str = "user",
        status: str = "active",
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none(
            {
                "id": _to_str(principal_uuid),
                "kind": kind,
                "status": status,
                "display_name": display_name,
                "email": email,
            }
        )
        return await self._client._request(
            "POST",
            "/principals",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def list(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        return await self._client._request(
            "GET",
            "/principals",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

class ResourcesClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create(
        self,
        resource_type: str,
        parent_id: str | UUID,
        name: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {
            "type": resource_type,
            "parent_id": str(parent_id),
            "name": name,
            "metadata": metadata or {},
        }
        return await self._client._request(
            "POST",
            "/resources",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def get(
        self,
        resource_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "GET",
            f"/resources/{resource_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def list_children(
        self,
        resource_id: str | UUID,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        params = _drop_none({"limit": limit, "cursor": cursor})
        return await self._client._request(
            "GET",
            f"/resources/{resource_id}/children",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def update(
        self,
        resource_id: str | UUID,
        *,
        name: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        if name is None and status is None and metadata is None:
            raise ValueError("At least one field must be provided for update")
        payload = _drop_none(
            {"name": name, "status": status, "metadata": metadata}
        )
        return await self._client._request(
            "PATCH",
            f"/resources/{resource_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def move(
        self,
        resource_id: str | UUID,
        new_parent_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {"new_parent_id": str(new_parent_id)}
        return await self._client._request(
            "POST",
            f"/resources/{resource_id}/move",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def delete(
        self,
        resource_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "DELETE",
            f"/resources/{resource_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

class RefsClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create_branch(
        self,
        resource_id: str | UUID,
        ref_name: str,
        *,
        from_ref: str = "main",
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {"ref_name": ref_name, "from_ref": from_ref}
        return await self._client._request(
            "POST",
            f"/refs/{resource_id}/branches",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def list_branches(
        self,
        resource_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        return await self._client._request(
            "GET",
            f"/refs/{resource_id}/branches",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def delete_branch(
        self,
        resource_id: str | UUID,
        ref_name: str,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "DELETE",
            f"/refs/{resource_id}/branches/{ref_name}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

class MergeRequestsClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create(
        self,
        target_resource_id: str | UUID,
        source_ref: str,
        *,
        target_ref: str = "main",
        title: Optional[str] = None,
        description: Optional[str] = None,
        required_approvals: int = 1,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none(
            {
                "target_resource_id": str(target_resource_id),
                "source_ref": source_ref,
                "target_ref": target_ref,
                "title": title,
                "description": description,
                "required_approvals": required_approvals,
            }
        )
        return await self._client._request(
            "POST",
            "/merge-requests",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def get(
        self,
        mr_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "GET",
            f"/merge-requests/{mr_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def approve(
        self,
        mr_id: str | UUID,
        decision: str,
        *,
        comment: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none({"decision": decision, "comment": comment})
        return await self._client._request(
            "POST",
            f"/merge-requests/{mr_id}/approve",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def merge(
        self,
        mr_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "POST",
            f"/merge-requests/{mr_id}/merge",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

class PromotionsClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create(
        self,
        moving_resource_id: str | UUID,
        to_scope_id: str | UUID,
        mode: str,
        *,
        placement: Optional[Dict[str, Any]] = None,
        rbac_template_ref: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none(
            {
                "moving_resource_id": str(moving_resource_id),
                "to_scope_id": str(to_scope_id),
                "mode": mode,
                "placement": placement or {},
                "rbac_template_ref": rbac_template_ref,
            }
        )
        return await self._client._request(
            "POST",
            "/promotions",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def get(
        self,
        pr_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "GET",
            f"/promotions/{pr_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def approve(
        self,
        pr_id: str | UUID,
        decision: str,
        *,
        comment: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none({"decision": decision, "comment": comment})
        return await self._client._request(
            "POST",
            f"/promotions/{pr_id}/approve",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def execute(
        self,
        pr_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "POST",
            f"/promotions/{pr_id}/execute",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

class RbacClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def grant(
        self,
        subject_principal_id: str | UUID,
        role_name: str,
        scope_resource_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {
            "principal_id": str(subject_principal_id),
            "role_name": role_name,
            "scope_resource_id": str(scope_resource_id),
        }
        return await self._client._request(
            "POST",
            "/rbac/grants",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def revoke(
        self,
        binding_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "DELETE",
            f"/rbac/grants/{binding_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def list_grants(
        self,
        resource_id: str | UUID,
        *,
        subject_principal_id: Optional[str | UUID] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> list[Dict[str, Any]]:
        params = _drop_none(
            {
                "resource_id": str(resource_id),
                "principal_id": _to_str(subject_principal_id),
            }
        )
        return await self._client._request(
            "GET",
            "/rbac/grants",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def effective(
        self,
        resource_id: str | UUID,
        *,
        subject_principal_id: Optional[str | UUID] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        params = _drop_none(
            {
                "resource_id": str(resource_id),
                "principal_id": _to_str(subject_principal_id),
            }
        )
        return await self._client._request(
            "GET",
            "/rbac/effective",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

class ActivitiesClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def list(
        self,
        *,
        resource_id: Optional[str | UUID] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        params = _drop_none(
            {
                "resource_id": _to_str(resource_id),
                "limit": limit,
                "cursor": cursor,
            }
        )
        return await self._client._request(
            "GET",
            "/activities",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

class ChatClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create_channel(
        self,
        parent_id: str | UUID,
        channel_kind: str,
        name: str,
        *,
        topic: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {
            "parent_id": str(parent_id),
            "channel_kind": channel_kind,
            "name": name,
            "topic": topic,
            "settings": settings or {},
        }
        return await self._client._request(
            "POST",
            "/chat/channels",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def list_messages(
        self,
        channel_id: str | UUID,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        params = _drop_none({"limit": limit, "cursor": cursor})
        return await self._client._request(
            "GET",
            f"/chat/channels/{channel_id}/messages",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def send_message(
        self,
        channel_id: str | UUID,
        body: str,
        *,
        body_json: Optional[Dict[str, Any]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none({"body": body, "body_json": body_json})
        return await self._client._request(
            "POST",
            f"/chat/channels/{channel_id}/messages",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
            headers=headers,
        )

    async def edit_message(
        self,
        message_id: str | UUID,
        body: str,
        *,
        body_json: Optional[Dict[str, Any]] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = _drop_none({"body": body, "body_json": body_json})
        return await self._client._request(
            "PATCH",
            f"/chat/messages/{message_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def delete_message(
        self,
        message_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        return await self._client._request(
            "DELETE",
            f"/chat/messages/{message_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def read_channel(
        self,
        channel_id: str | UUID,
        last_read_message_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        payload = {"last_read_message_id": str(last_read_message_id)}
        return await self._client._request(
            "POST",
            f"/chat/channels/{channel_id}/read",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )
