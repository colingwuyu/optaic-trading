"""Tests for guardrails API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app


@pytest.mark.asyncio
async def test_get_bundle_not_found():
    """Test GET bundle returns empty when no bundle exists."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/guardrails/resources/nonexistent-resource/bundle")
        assert response.status_code == 200
        data = response.json()
        assert data["bundle"] is None


@pytest.mark.asyncio
async def test_put_and_get_bundle():
    """Test PUT bundle then GET returns the same bundle."""
    resource_id = f"resource-{uuid4()}"
    bundle_id = f"bundle-{uuid4()}"

    bundle_data = {
        "bundle_id": bundle_id,
        "resource_id": resource_id,
        "resource_version_id": None,
        "created_by": "test_user",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contracts": [
            {
                "ref": {
                    "contract_kind": "test",
                    "contract_name": "test_contract",
                    "version": "1.0.0",
                    "json_schema": "{}",
                },
                "config_json": "{}",
                "contract_hash": "abc123",
                "enforcement_hint": "warn",
            }
        ],
        "notes": "Test bundle",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # PUT the bundle
        put_response = await client.put(
            f"/guardrails/resources/{resource_id}/bundle",
            json={"bundle": bundle_data},
        )
        assert put_response.status_code == 200
        put_data = put_response.json()
        assert put_data["bundle"]["bundle_id"] == bundle_id

        # GET the bundle
        get_response = await client.get(
            f"/guardrails/resources/{resource_id}/bundle"
        )
        assert get_response.status_code == 200
        get_data = get_response.json()
        assert get_data["bundle"] is not None
        assert get_data["bundle"]["bundle_id"] == bundle_id
        assert get_data["bundle"]["resource_id"] == resource_id
        assert len(get_data["bundle"]["contracts"]) == 1


@pytest.mark.asyncio
async def test_put_bundle_resource_id_mismatch():
    """Test PUT bundle fails when resource_id in path doesn't match bundle."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        bundle_data = {
            "bundle_id": "bundle-mismatch",
            "resource_id": "resource-in-body",  # Different from path
            "created_by": "test_user",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "contracts": [],
        }

        response = await client.put(
            "/guardrails/resources/resource-in-path/bundle",
            json={"bundle": bundle_data},
        )
        assert response.status_code == 400
        assert "does not match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_reports_empty():
    """Test GET reports returns empty list when no reports exist."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/guardrails/reports",
            params={"target_id": "nonexistent-target"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reports"] == []


@pytest.mark.asyncio
async def test_list_reports_with_filters():
    """Test GET reports with scope and target_id filters."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Test with filters (no reports expected)
        response = await client.get(
            "/guardrails/reports",
            params={"scope": "resource", "target_id": "test-target", "limit": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["reports"], list)
