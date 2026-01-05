from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import UUID

import httpx

if TYPE_CHECKING:
    from .admin import AdminClient
    from .datasets import DatasetsClient
    from .definitions import DefinitionsClient
    from .experiments import ExperimentsClient
    from .governance import GovernanceClient
    from .ops import OpsClient
    from .pipelines import PipelinesClient
    from .signals import SignalsClient


def _to_str(value: Optional[str | UUID]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


class AsyncPlatformClient:
    """Async Python SDK client for OptAIC platform.

    Supports three authentication methods (in priority order):
    1. API Key: Use `api_key` parameter for SDK/production use
    2. OAuth Token: Use `oauth_token` parameter for GUI/user sessions
    3. Dev Mode: Use `principal_id` and `tenant_id` for development

    Examples:
        # API Key authentication (recommended for SDK)
        client = AsyncPlatformClient(
            base_url="https://api.optaic.com",
            api_key="optaic_abc123.secret..."
        )

        # Dev mode authentication (for local development)
        client = AsyncPlatformClient(
            base_url="http://localhost:8000",
            principal_id="...",
            tenant_id="..."
        )
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        oauth_token: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the SDK client.

        Args:
            base_url: API base URL (e.g., "https://api.optaic.com")
            api_key: API key for authentication (format: optaic_xxx.secret)
            oauth_token: OAuth bearer token for authentication
            principal_id: Principal ID for dev mode authentication
            tenant_id: Tenant ID for dev mode authentication
            client: Optional httpx client instance (for testing)
            timeout: Request timeout in seconds
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._oauth_token = oauth_token
        self._principal_id = _to_str(principal_id)
        self._tenant_id = _to_str(tenant_id)
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout
        )
        # Core platform clients
        self.health = HealthClient(self)
        self.auth = AuthClient(self)
        self.tenants = TenantsClient(self)
        self.principals = PrincipalsClient(self)
        self.resources = ResourcesClient(self)
        self.refs = RefsClient(self)
        self.merge_requests = MergeRequestsClient(self)
        self.promotions = PromotionsClient(self)
        self.rbac = RbacClient(self)
        self.activities = ActivitiesClient(self)
        self.chat = ChatClient(self)

        # Admin client (lazy-loaded)
        self._admin: "AdminClient | None" = None

        # Governance client (lazy-loaded)
        self._governance: "GovernanceClient | None" = None

        # Quant domain clients (lazy-loaded)
        self._ops: "OpsClient | None" = None
        self._datasets: "DatasetsClient | None" = None
        self._signals: "SignalsClient | None" = None
        self._pipelines: "PipelinesClient | None" = None
        self._experiments: "ExperimentsClient | None" = None
        self._definitions: "DefinitionsClient | None" = None

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

    def set_api_key(self, api_key: Optional[str]) -> None:
        """Set the API key for authentication."""
        self._api_key = api_key

    def set_oauth_token(self, oauth_token: Optional[str]) -> None:
        """Set the OAuth token for authentication."""
        self._oauth_token = oauth_token

    def _headers(
        self,
        principal_id: Optional[str | UUID],
        tenant_id: Optional[str | UUID],
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Build request headers with authentication.

        Authentication priority:
        1. API Key (X-API-Key header)
        2. OAuth Token (Authorization: Bearer header)
        3. Dev mode (X-Principal-Id, X-Tenant-Id headers)
        """
        headers: Dict[str, str] = {}

        # Priority 1: API Key authentication
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        # Priority 2: OAuth Token authentication
        elif self._oauth_token:
            headers["Authorization"] = f"Bearer {self._oauth_token}"

        # For dev mode or additional context, include principal/tenant headers
        # These are also used by some API endpoints even with API key auth
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
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make an HTTP request.

        Args:
            method: HTTP method
            path: URL path
            principal_id: Override principal ID
            tenant_id: Override tenant ID
            params: Query parameters
            json: JSON body (for application/json)
            headers: Additional headers
            files: Files for multipart upload (e.g., {"file": ("name", bytes, "type")})
            data: Form data for multipart upload

        Returns:
            Response JSON or None for 204
        """
        request_kwargs: Dict[str, Any] = {
            "headers": self._headers(principal_id, tenant_id, headers),
        }
        if params is not None:
            request_kwargs["params"] = params
        if json is not None:
            request_kwargs["json"] = json
        if files is not None:
            request_kwargs["files"] = files
        if data is not None:
            request_kwargs["data"] = data

        response = await self._client.request(method, path, **request_kwargs)
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    # --- Admin Client (lazy-loaded) ---

    @property
    def admin(self) -> "AdminClient":
        """Admin client for user and space management."""
        if self._admin is None:
            from .admin import AdminClient

            self._admin = AdminClient(self)
        return self._admin

    @property
    def governance(self) -> "GovernanceClient":
        """Governance client for copy, branch, transfer, promote, merge operations."""
        if self._governance is None:
            from .governance import GovernanceClient

            self._governance = GovernanceClient(self)
        return self._governance

    # --- Quant Domain Clients (lazy-loaded) ---

    @property
    def ops(self) -> "OpsClient":
        """Operators client for expression evaluation."""
        if self._ops is None:
            from .ops import OpsClient

            self._ops = OpsClient(self)
        return self._ops

    @property
    def datasets(self) -> "DatasetsClient":
        """Datasets client for data preview and refresh."""
        if self._datasets is None:
            from .datasets import DatasetsClient

            self._datasets = DatasetsClient(self)
        return self._datasets

    @property
    def signals(self) -> "SignalsClient":
        """Signals client for signal registration and promotion."""
        if self._signals is None:
            from .signals import SignalsClient

            self._signals = SignalsClient(self)
        return self._signals

    @property
    def pipelines(self) -> "PipelinesClient":
        """Pipelines client for definition and instance management."""
        if self._pipelines is None:
            from .pipelines import PipelinesClient

            self._pipelines = PipelinesClient(self)
        return self._pipelines

    @property
    def experiments(self) -> "ExperimentsClient":
        """Experiments client for expression experiments and macros."""
        if self._experiments is None:
            from .experiments import ExperimentsClient

            self._experiments = ExperimentsClient(self)
        return self._experiments

    @property
    def definitions(self) -> "DefinitionsClient":
        """Definitions client for plugin upload and management."""
        if self._definitions is None:
            from .definitions import DefinitionsClient

            self._definitions = DefinitionsClient(self)
        return self._definitions


class HealthClient:
    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def get(self) -> Dict[str, Any]:
        return await self._client._request("GET", "/healthz")


class AuthClient:
    """Client for authentication management operations."""

    def __init__(self, client: AsyncPlatformClient) -> None:
        self._client = client

    async def create_api_key(
        self,
        name: str,
        *,
        description: Optional[str] = None,
        scopes: Optional[list[str]] = None,
        expires_in_days: Optional[int] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Create a new API key.

        Args:
            name: Human-readable name for the key
            description: Optional description
            scopes: Optional permission scopes
            expires_in_days: Optional expiry in days (max 365)
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Created API key including the full key (shown only once)
        """
        payload = _drop_none(
            {
                "name": name,
                "description": description,
                "scopes": scopes,
                "expires_in_days": expires_in_days,
            }
        )
        return await self._client._request(
            "POST",
            "/auth/keys",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
        )

    async def list_api_keys(
        self,
        *,
        include_revoked: bool = False,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """List API keys for the current principal.

        Args:
            include_revoked: Include revoked keys in the list
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            List of API keys (without secrets)
        """
        params = {"include_revoked": str(include_revoked).lower()}
        return await self._client._request(
            "GET",
            "/auth/keys",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )

    async def get_api_key(
        self,
        key_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get details for a specific API key.

        Args:
            key_id: API key ID
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            API key details (without secret)
        """
        return await self._client._request(
            "GET",
            f"/auth/keys/{key_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def revoke_api_key(
        self,
        key_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Revoke an API key.

        Args:
            key_id: API key ID to revoke
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Revoked API key details
        """
        return await self._client._request(
            "DELETE",
            f"/auth/keys/{key_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def get_current_user(
        self,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get information about the currently authenticated user.

        Returns:
            Current user info including principal_id, tenant_id, and auth_method
        """
        return await self._client._request(
            "GET",
            "/auth/me",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )


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

    async def get(
        self,
        tenant_id_to_get: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get details for a specific tenant.

        Args:
            tenant_id_to_get: Tenant ID to retrieve
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            Tenant details including root_resource_id
        """
        return await self._client._request(
            "GET",
            f"/tenants/{tenant_id_to_get}",
            principal_id=principal_id,
            tenant_id=tenant_id,
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
        payload = _drop_none({"name": name, "status": status, "metadata": metadata})
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

    async def copy(
        self,
        resource_id: str | UUID,
        target_parent_id: str | UUID,
        *,
        new_name: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Copy a resource to a new location.

        Creates a copy of the source resource under the target parent.
        The copy will have a derived_from lineage edge to the source.

        Args:
            resource_id: Source resource to copy
            target_parent_id: Target parent for the copy
            new_name: Optional new name (defaults to source name)
            principal_id: Override principal for auth
            tenant_id: Override tenant for auth

        Returns:
            The created copy resource
        """
        payload = _drop_none(
            {
                "target_parent_id": str(target_parent_id),
                "new_name": new_name,
            }
        )
        return await self._client._request(
            "POST",
            f"/resources/{resource_id}/copy",
            principal_id=principal_id,
            tenant_id=tenant_id,
            json=payload,
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
