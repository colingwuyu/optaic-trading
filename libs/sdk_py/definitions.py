"""Definitions SDK client.

Provides methods for:
- Uploading definition plugins (ZIP files)
- Deploying draft definitions
- Re-running tests
- Listing and viewing definitions
"""

from __future__ import annotations

from pathlib import Path
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


class DefinitionsClient:
    """Client for definition upload and management operations."""

    def __init__(self, client: "AsyncPlatformClient") -> None:
        self._client = client

    async def upload(
        self,
        zip_path: str | Path,
        *,
        target_parent_id: Optional[str | UUID] = None,
        skip_tests: bool = False,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Upload a definition plugin from a ZIP file.

        The ZIP must contain a manifest.json with required fields:
        - name: Definition name
        - version: Semantic version
        - definition_type: PipelineDef, StoreDef, AccessorDef, OpDef, etc.
        - module_file: Python file containing the class
        - class_name: Class to register in factory
        - interface_spec: Interface the class implements

        Optional fields:
        - test_suite_file: pytest file for tests
        - category: Definition category
        - description: Human-readable description

        Args:
            zip_path: Path to ZIP file containing the definition plugin
            target_parent_id: Parent resource ID (Project or Space)
            skip_tests: Skip test execution
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Upload result with id, name, version, definition_type, code_ref,
            status, evaluation_status, artifact_ref, test results, and issues
        """
        path = Path(zip_path)
        if not path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        if not path.suffix.lower() == ".zip":
            raise ValueError("File must be a ZIP archive (.zip)")

        # Read file content
        content = path.read_bytes()
        filename = path.name

        # Build form data
        files = {"file": (filename, content, "application/zip")}
        data: Dict[str, Any] = {}

        if target_parent_id is not None:
            data["target_parent_id"] = str(target_parent_id)

        if skip_tests:
            data["skip_tests"] = "true"

        return await self._client._request(
            "POST",
            "/definitions/upload",
            principal_id=principal_id,
            tenant_id=tenant_id,
            files=files,
            data=data,
        )

    async def upload_bytes(
        self,
        zip_content: bytes,
        filename: str = "upload.zip",
        *,
        target_parent_id: Optional[str | UUID] = None,
        skip_tests: bool = False,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Upload a definition plugin from bytes.

        Args:
            zip_content: ZIP file content as bytes
            filename: Original filename (default "upload.zip")
            target_parent_id: Parent resource ID (Project or Space)
            skip_tests: Skip test execution
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Upload result
        """
        files = {"file": (filename, zip_content, "application/zip")}
        data: Dict[str, Any] = {}

        if target_parent_id is not None:
            data["target_parent_id"] = str(target_parent_id)

        if skip_tests:
            data["skip_tests"] = "true"

        return await self._client._request(
            "POST",
            "/definitions/upload",
            principal_id=principal_id,
            tenant_id=tenant_id,
            files=files,
            data=data,
        )

    async def deploy(
        self,
        definition_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Deploy a draft definition.

        Changes status from draft to active and registers plugin in factory.
        Only draft definitions can be deployed.

        Args:
            definition_id: Definition resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Deployment result with id, name, code_ref, status
        """
        return await self._client._request(
            "POST",
            f"/definitions/{definition_id}/deploy",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def rerun_tests(
        self,
        definition_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Re-run tests for a definition.

        Runs the test suite again and updates evaluation status.
        If tests pass and status is draft, automatically deploys.

        Args:
            definition_id: Definition resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Test results with evaluation_status, test counts, duration, failures
        """
        return await self._client._request(
            "POST",
            f"/definitions/{definition_id}/rerun-tests",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def get(
        self,
        definition_id: str | UUID,
        *,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """Get detailed information about a definition upload.

        Includes manifest, test results, and file info.

        Args:
            definition_id: Definition resource ID
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Definition details including manifest, test results, timestamps
        """
        return await self._client._request(
            "GET",
            f"/definitions/{definition_id}",
            principal_id=principal_id,
            tenant_id=tenant_id,
        )

    async def list(
        self,
        *,
        definition_type: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        parent_id: Optional[str | UUID] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        principal_id: Optional[str | UUID] = None,
        tenant_id: Optional[str | UUID] = None,
    ) -> Dict[str, Any]:
        """List definition resources.

        Returns all Definition resources the actor can read.
        Supports filtering by type, status, category, and parent.

        Args:
            definition_type: Filter by type (PipelineDef, StoreDef, etc.)
            status: Filter by status ("draft", "active")
            category: Filter by category
            parent_id: Filter by parent resource
            limit: Maximum results (default 50, max 200)
            cursor: Pagination cursor
            principal_id: Override principal ID for this request
            tenant_id: Override tenant ID for this request

        Returns:
            Dict with items (list of definitions) and next_cursor
        """
        params = _drop_none(
            {
                "definition_type": definition_type,
                "status": status,
                "category": category,
                "parent_id": _to_str(parent_id),
                "limit": limit,
                "cursor": cursor,
            }
        )
        return await self._client._request(
            "GET",
            "/definitions",
            principal_id=principal_id,
            tenant_id=tenant_id,
            params=params,
        )
