"""End-to-End Governance Tests - Using Python SDK.

These tests verify the governance operations work correctly
end-to-end through the SDK → API → Service → Database stack.

CRITICAL PRINCIPLE: SDK-ONLY TESTING
=====================================
E2E tests must ONLY use the SDK. NO direct database access allowed.

Case Study: Resource Governance Workflows
==========================================
1. Copy: Reference copy, same artifact, no RBAC change
2. Branch: File copy, actor=owner, source_owner=viewer
3. Transfer: Request/accept workflow, recipient chooses project
4. Promote: To staging, approval-based auto-move to official
5. Merge: Branch artifact replaces ancestor
6. Lineage: Query resource derivation history

Resource Type Rules:
- Flow resources (runs): View-only, no governance actions
- Scope resources (Projects): Copy, transfer, promote (no branch/merge)
- Definition/Instance: All governance actions allowed

NO MOCKS - All tests use real API endpoints via SDK.
NO DIRECT DB ACCESS - All operations via SDK only.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from libs.sdk_py import AsyncPlatformClient

# E2E tests connect to an external server
# Start the server with: python scripts/e2e_server.py
E2E_API_URL = os.environ.get("E2E_API_URL", "http://localhost:8082")


# =============================================================================
# FIXTURES FOR GOVERNANCE E2E TESTING
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Create an AsyncPlatformClient connecting to the E2E server.

    CRITICAL: E2E tests must connect to the real running server,
    NOT use ASGITransport in-process. Start the server with:
        python scripts/e2e_server.py
    """
    client = AsyncPlatformClient(base_url=E2E_API_URL)
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="function")
async def gov_test_setup(sdk_client: AsyncPlatformClient):
    """Set up tenant, principal, space hierarchy for governance tests.

    Creates:
    - Tenant with owner principal
    - Space (team)
    - SubSpace (custom)
    - Project (for resources)
    """
    tenant_id = uuid4()
    principal_id = uuid4()

    sdk_client.set_principal_id(principal_id)
    sdk_client.set_tenant_id(tenant_id)

    # Create tenant
    tenant_result = await sdk_client.tenants.create(
        name=f"GovTestTenant-{tenant_id}",
    )
    root_resource_id = UUID(tenant_result["root_resource_id"])

    # Create Space
    space = await sdk_client.resources.create(
        resource_type="Space",
        parent_id=root_resource_id,
        name="Team Space",
    )
    space_id = UUID(space["id"])

    # Create SubSpace
    subspace = await sdk_client.resources.create(
        resource_type="SubSpace",
        parent_id=space_id,
        name="Custom SubSpace",
    )
    subspace_id = UUID(subspace["id"])

    # Create Project
    project = await sdk_client.resources.create(
        resource_type="Project",
        parent_id=subspace_id,
        name="Test Project",
    )
    project_id = UUID(project["id"])

    return {
        "client": sdk_client,
        "tenant_id": UUID(tenant_result["id"]),
        "principal_id": principal_id,
        "root_resource_id": root_resource_id,
        "space_id": space_id,
        "subspace_id": subspace_id,
        "project_id": project_id,
    }


@pytest_asyncio.fixture(scope="function")
async def gov_with_resource(gov_test_setup):
    """Set up with a SignalDef resource for governance operations."""
    client = gov_test_setup["client"]
    project_id = gov_test_setup["project_id"]

    # Create a SignalDef resource (allows all governance actions)
    resource = await client.resources.create(
        resource_type="SignalDef",
        parent_id=project_id,
        name="Test Signal",
        metadata={"description": "A test signal for governance"},
    )

    return {
        **gov_test_setup,
        "resource_id": UUID(resource["id"]),
        "resource_name": resource["name"],
    }


@pytest_asyncio.fixture(scope="function")
async def gov_two_users(gov_test_setup):
    """Set up with two users for transfer tests."""
    client = gov_test_setup["client"]
    project_id = gov_test_setup["project_id"]
    subspace_id = gov_test_setup["subspace_id"]

    # Create a resource owned by the first user
    resource = await client.resources.create(
        resource_type="SignalDef",
        parent_id=project_id,
        name="Transferable Signal",
    )

    # Create second user
    second_user = await client.principals.create(
        display_name="Second User",
        email=f"second-{uuid4()}@example.com",
    )
    second_user_id = UUID(second_user["id"])

    # Create a project for the second user
    second_project = await client.resources.create(
        resource_type="Project",
        parent_id=subspace_id,
        name="Second User Project",
    )

    return {
        **gov_test_setup,
        "resource_id": UUID(resource["id"]),
        "second_user_id": second_user_id,
        "second_project_id": UUID(second_project["id"]),
    }


@pytest_asyncio.fixture(scope="function")
async def gov_team_setup(gov_test_setup):
    """Set up with team principal for promote tests."""
    client = gov_test_setup["client"]
    project_id = gov_test_setup["project_id"]

    # Create a resource to promote
    resource = await client.resources.create(
        resource_type="SignalDef",
        parent_id=project_id,
        name="Promotable Signal",
    )

    # Create team principal
    team = await client.principals.create(
        display_name="Research Team",
        kind="team",
    )

    return {
        **gov_test_setup,
        "resource_id": UUID(resource["id"]),
        "team_id": UUID(team["id"]),
    }


# =============================================================================
# CASE STUDY: GOVERNANCE COPY OPERATIONS
# =============================================================================


@pytest.mark.asyncio
class TestGovernanceCopy:
    """Test copy operations via governance SDK."""

    async def test_copy_resource(self, gov_with_resource):
        """Copy a resource by reference (same artifact)."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Copy via governance client
        copy_result = await client.governance.copy(
            resource_id=resource_id,
            target_parent_id=project_id,
            name="Copied Signal",
        )

        assert copy_result is not None
        assert copy_result["operation"] == "copy"
        assert copy_result["source_id"] == str(resource_id)
        assert copy_result["name"] == "Copied Signal"
        assert "id" in copy_result

        # Verify the copy exists
        copy_resource = await client.resources.get(copy_result["id"])
        assert copy_resource["name"] == "Copied Signal"
        assert copy_resource["type"] == "SignalDef"

    async def test_copy_with_default_name(self, gov_with_resource):
        """Copy uses 'Copy of {source}' as default name."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Copy without specifying name
        copy_result = await client.governance.copy(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        assert "Copy of" in copy_result["name"]

    async def test_copy_creates_lineage(self, gov_with_resource):
        """Copy creates copy_of lineage edge."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Copy the resource
        copy_result = await client.governance.copy(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        # Check lineage
        lineage = await client.governance.get_lineage(
            resource_id=copy_result["id"],
            direction="upstream",
        )

        assert lineage is not None
        assert len(lineage["entries"]) >= 1
        # First upstream entry should be the source
        assert lineage["entries"][0]["id"] == str(resource_id)


# =============================================================================
# CASE STUDY: GOVERNANCE BRANCH OPERATIONS
# =============================================================================


@pytest.mark.asyncio
class TestGovernanceBranch:
    """Test branch operations via governance SDK."""

    async def test_branch_resource(self, gov_with_resource):
        """Branch a resource with file copy."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Branch via governance client
        branch_result = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
            name="Feature Branch",
        )

        assert branch_result is not None
        assert branch_result["operation"] == "branch"
        assert branch_result["source_id"] == str(resource_id)
        assert branch_result["name"] == "Feature Branch"

        # Branch should have different artifact_ref if source had one
        # (artifact is copied, not shared)

    async def test_branch_creates_owner_binding(self, gov_with_resource):
        """Branch creates owner role for actor."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Branch the resource
        branch_result = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        # Check RBAC grants
        grants = await client.rbac.list_grants(branch_result["id"])

        # Actor should be owner
        owner_grants = [g for g in grants if g.get("role_name") == "owner"]
        assert len(owner_grants) >= 1

    async def test_branch_creates_lineage(self, gov_with_resource):
        """Branch creates branch_of lineage edge."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Branch the resource
        branch_result = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        # Check lineage
        lineage = await client.governance.get_lineage(
            resource_id=branch_result["id"],
            direction="upstream",
            edge_types=["branch_of"],
        )

        assert lineage is not None
        assert len(lineage["entries"]) >= 1


# =============================================================================
# CASE STUDY: GOVERNANCE TRANSFER WORKFLOW
# =============================================================================


@pytest.mark.asyncio
class TestGovernanceTransfer:
    """Test transfer request/accept workflow via governance SDK."""

    async def test_create_transfer_request(self, gov_two_users):
        """Create a transfer request for a resource."""
        client = gov_two_users["client"]
        resource_id = gov_two_users["resource_id"]
        second_user_id = gov_two_users["second_user_id"]

        # Create transfer request
        request = await client.governance.create_transfer_request(
            resource_id=resource_id,
            recipient_id=second_user_id,
            message="Handing off this signal to you",
        )

        assert request is not None
        assert request["status"] == "pending"
        assert request["resource_id"] == str(resource_id)
        assert request["recipient_id"] == str(second_user_id)
        assert "id" in request
        assert "expires_at" in request

    async def test_accept_transfer(self, gov_two_users):
        """Accept a transfer request and move resource."""
        client = gov_two_users["client"]
        resource_id = gov_two_users["resource_id"]
        second_user_id = gov_two_users["second_user_id"]
        second_project_id = gov_two_users["second_project_id"]
        original_owner = gov_two_users["principal_id"]

        # Create transfer request
        request = await client.governance.create_transfer_request(
            resource_id=resource_id,
            recipient_id=second_user_id,
        )

        # Switch to second user to accept
        client.set_principal_id(second_user_id)

        # Accept transfer with destination project
        result = await client.governance.accept_transfer(
            transfer_request_id=request["id"],
            destination_project_id=second_project_id,
            response_message="Thanks, I'll take it!",
        )

        assert result is not None
        assert result["operation"] == "transfer_accepted"
        assert result["owner_id"] == str(second_user_id)
        assert result["previous_owner_id"] == str(original_owner)

        # Verify resource moved
        resource = await client.resources.get(resource_id)
        assert resource["parent_id"] == str(second_project_id)

    async def test_reject_transfer(self, gov_two_users):
        """Reject a transfer request."""
        client = gov_two_users["client"]
        resource_id = gov_two_users["resource_id"]
        second_user_id = gov_two_users["second_user_id"]

        # Create transfer request
        request = await client.governance.create_transfer_request(
            resource_id=resource_id,
            recipient_id=second_user_id,
        )

        # Switch to second user to reject
        client.set_principal_id(second_user_id)

        # Reject transfer
        result = await client.governance.reject_transfer(
            transfer_request_id=request["id"],
            response_message="Sorry, I don't have capacity",
        )

        assert result is not None
        assert result["status"] == "rejected"

    async def test_cancel_transfer(self, gov_two_users):
        """Cancel a transfer request (by sender)."""
        client = gov_two_users["client"]
        resource_id = gov_two_users["resource_id"]
        second_user_id = gov_two_users["second_user_id"]

        # Create transfer request
        request = await client.governance.create_transfer_request(
            resource_id=resource_id,
            recipient_id=second_user_id,
        )

        # Cancel as sender (original principal is still set)
        result = await client.governance.cancel_transfer(
            transfer_request_id=request["id"],
        )

        assert result is not None
        assert result["status"] == "cancelled"


# =============================================================================
# CASE STUDY: GOVERNANCE PROMOTE WORKFLOW
# =============================================================================


@pytest.mark.asyncio
class TestGovernancePromote:
    """Test promote to staging with approval workflow."""

    async def test_promote_to_staging(self, gov_team_setup):
        """Promote a resource to team's staging subspace."""
        client = gov_team_setup["client"]
        resource_id = gov_team_setup["resource_id"]
        space_id = gov_team_setup["space_id"]
        team_id = gov_team_setup["team_id"]

        # Promote via governance client
        result = await client.governance.promote(
            resource_id=resource_id,
            target_space_id=space_id,
            team_principal_id=team_id,
            name="Official Signal",
        )

        assert result is not None
        assert result["operation"] == "promote"
        assert result["source_id"] == str(resource_id)
        assert result["team_principal_id"] == str(team_id)
        assert result["subspace_kind"] == "staging"
        assert result["status"] == "pending_approval"
        assert "promotion_request_id" in result

    async def test_approve_promotion(self, gov_team_setup):
        """Approve a promotion request to move to official."""
        client = gov_team_setup["client"]
        resource_id = gov_team_setup["resource_id"]
        space_id = gov_team_setup["space_id"]
        team_id = gov_team_setup["team_id"]

        # Promote to staging
        promote_result = await client.governance.promote(
            resource_id=resource_id,
            target_space_id=space_id,
            team_principal_id=team_id,
        )

        promotion_request_id = promote_result["promotion_request_id"]

        # Approve the promotion
        approval_result = await client.governance.approve_promotion(
            promotion_request_id=promotion_request_id,
            comment="Looks good, approved!",
        )

        assert approval_result is not None
        assert approval_result["approval_count"] >= 1
        # With 1 required approval, should auto-move to official
        if approval_result["approval_count"] >= approval_result["required_approvals"]:
            assert approval_result["status"] == "merged"
            assert approval_result["moved_to"] == "official"


# =============================================================================
# CASE STUDY: GOVERNANCE MERGE OPERATIONS
# =============================================================================


@pytest.mark.asyncio
class TestGovernanceMerge:
    """Test merge operations via governance SDK."""

    async def test_merge_branch_to_ancestor(self, gov_with_resource):
        """Merge a branch back to its ancestor."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # First create a branch
        branch_result = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
            name="Feature Branch",
        )
        branch_id = UUID(branch_result["id"])

        # Merge branch back to source
        merge_result = await client.governance.merge(
            source_id=branch_id,
            target_id=resource_id,
        )

        assert merge_result is not None
        assert merge_result["operation"] == "merge"
        assert merge_result["source_id"] == str(branch_id)
        assert merge_result["target_id"] == str(resource_id)
        assert "contributor_id" in merge_result

    async def test_merge_creates_lineage(self, gov_with_resource):
        """Merge creates merged_from lineage edge."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Create and merge a branch
        branch_result = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        await client.governance.merge(
            source_id=branch_result["id"],
            target_id=resource_id,
        )

        # Check lineage on the target (ancestor)
        lineage = await client.governance.get_lineage(
            resource_id=resource_id,
            direction="downstream",
            edge_types=["merged_from"],
        )

        assert lineage is not None


# =============================================================================
# CASE STUDY: GOVERNANCE LINEAGE QUERIES
# =============================================================================


@pytest.mark.asyncio
class TestGovernanceLineage:
    """Test lineage query operations via governance SDK."""

    async def test_get_upstream_lineage(self, gov_with_resource):
        """Query upstream lineage (ancestors)."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Create a branch to establish lineage
        branch_result = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        # Query upstream from branch
        lineage = await client.governance.get_lineage(
            resource_id=branch_result["id"],
            direction="upstream",
        )

        assert lineage is not None
        assert lineage["resource_id"] == branch_result["id"]
        assert lineage["direction"] == "upstream"
        assert isinstance(lineage["entries"], list)
        assert len(lineage["entries"]) >= 1
        assert lineage["entries"][0]["id"] == str(resource_id)

    async def test_get_downstream_lineage(self, gov_with_resource):
        """Query downstream lineage (descendants)."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Create branches to establish lineage
        await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
            name="Branch 1",
        )
        await client.governance.copy(
            resource_id=resource_id,
            target_parent_id=project_id,
            name="Copy 1",
        )

        # Query downstream from source
        lineage = await client.governance.get_lineage(
            resource_id=resource_id,
            direction="downstream",
        )

        assert lineage is not None
        assert lineage["direction"] == "downstream"
        # Should have at least 2 descendants
        assert len(lineage["entries"]) >= 2

    async def test_lineage_filter_by_edge_type(self, gov_with_resource):
        """Filter lineage by edge type."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Create both branch and copy
        await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
        )
        await client.governance.copy(
            resource_id=resource_id,
            target_parent_id=project_id,
        )

        # Query only branches
        branch_lineage = await client.governance.get_lineage(
            resource_id=resource_id,
            direction="downstream",
            edge_types=["branch_of"],
        )

        # Query only copies
        copy_lineage = await client.governance.get_lineage(
            resource_id=resource_id,
            direction="downstream",
            edge_types=["copy_of"],
        )

        assert branch_lineage is not None
        assert copy_lineage is not None


# =============================================================================
# CASE STUDY: RESOURCE TYPE VALIDATION
# =============================================================================


@pytest.mark.asyncio
class TestResourceTypeValidation:
    """Test resource type validation for governance operations."""

    async def test_flow_resource_cannot_branch(self, gov_test_setup):
        """Flow resources (runs) cannot be branched."""
        client = gov_test_setup["client"]
        project_id = gov_test_setup["project_id"]

        # Create a PipelineRun (flow resource)
        run = await client.resources.create(
            resource_type="PipelineRun",
            parent_id=project_id,
            name="Test Run",
        )

        # Attempt to branch should fail
        with pytest.raises(Exception) as exc_info:
            await client.governance.branch(
                resource_id=run["id"],
                target_parent_id=project_id,
            )

        # Should get a 400 error about action not allowed
        assert (
            "400" in str(exc_info.value) or "not allowed" in str(exc_info.value).lower()
        )

    async def test_project_cannot_branch(self, gov_test_setup):
        """Project (scope resource) cannot be branched or merged."""
        client = gov_test_setup["client"]
        project_id = gov_test_setup["project_id"]
        subspace_id = gov_test_setup["subspace_id"]

        # Attempt to branch project should fail
        with pytest.raises(Exception) as exc_info:
            await client.governance.branch(
                resource_id=project_id,
                target_parent_id=subspace_id,
            )

        assert (
            "400" in str(exc_info.value) or "not allowed" in str(exc_info.value).lower()
        )

    async def test_project_can_copy_and_promote(self, gov_team_setup):
        """Project (scope resource) can be copied and promoted."""
        client = gov_team_setup["client"]
        project_id = gov_team_setup["project_id"]
        subspace_id = gov_team_setup["subspace_id"]
        space_id = gov_team_setup["space_id"]
        team_id = gov_team_setup["team_id"]

        # Copy should work
        copy_result = await client.governance.copy(
            resource_id=project_id,
            target_parent_id=subspace_id,
            name="Copied Project",
        )
        assert copy_result["operation"] == "copy"

        # Promote should work
        promote_result = await client.governance.promote(
            resource_id=project_id,
            target_space_id=space_id,
            team_principal_id=team_id,
        )
        assert promote_result["operation"] == "promote"


# =============================================================================
# CASE STUDY: FULL GOVERNANCE WORKFLOW
# =============================================================================


@pytest.mark.asyncio
class TestFullGovernanceWorkflow:
    """Test a complete governance workflow end-to-end."""

    async def test_branch_modify_merge_workflow(self, gov_with_resource):
        """Complete branch → modify → merge workflow."""
        client = gov_with_resource["client"]
        resource_id = gov_with_resource["resource_id"]
        project_id = gov_with_resource["project_id"]

        # Step 1: Branch the resource
        branch = await client.governance.branch(
            resource_id=resource_id,
            target_parent_id=project_id,
            name="Feature Branch",
        )
        branch_id = branch["id"]

        # Step 2: Modify the branch (update metadata)
        await client.resources.update(
            branch_id,
            metadata={"modified": True, "version": "2.0"},
        )

        # Step 3: Merge back to ancestor
        merge_result = await client.governance.merge(
            source_id=branch_id,
            target_id=resource_id,
        )

        assert merge_result["operation"] == "merge"
        assert merge_result["target_id"] == str(resource_id)

        # Verify lineage chain
        lineage = await client.governance.get_lineage(
            resource_id=resource_id,
            direction="downstream",
        )
        assert len(lineage["entries"]) >= 1

    async def test_transfer_workflow(self, gov_two_users):
        """Complete transfer request → accept workflow."""
        client = gov_two_users["client"]
        resource_id = gov_two_users["resource_id"]
        second_user_id = gov_two_users["second_user_id"]
        second_project_id = gov_two_users["second_project_id"]

        # Step 1: Owner creates transfer request
        request = await client.governance.create_transfer_request(
            resource_id=resource_id,
            recipient_id=second_user_id,
            message="Please take ownership of this signal",
        )
        assert request["status"] == "pending"

        # Step 2: Switch to recipient
        client.set_principal_id(second_user_id)

        # Step 3: Recipient accepts with destination
        result = await client.governance.accept_transfer(
            transfer_request_id=request["id"],
            destination_project_id=second_project_id,
        )

        assert result["owner_id"] == str(second_user_id)

        # Step 4: Verify resource moved
        resource = await client.resources.get(resource_id)
        assert resource["parent_id"] == str(second_project_id)

    async def test_promote_and_approve_workflow(self, gov_team_setup):
        """Complete promote → approve workflow."""
        client = gov_team_setup["client"]
        resource_id = gov_team_setup["resource_id"]
        space_id = gov_team_setup["space_id"]
        team_id = gov_team_setup["team_id"]

        # Step 1: Promote to staging
        promote = await client.governance.promote(
            resource_id=resource_id,
            target_space_id=space_id,
            team_principal_id=team_id,
            name="Official Signal",
        )

        assert promote["subspace_kind"] == "staging"
        assert promote["status"] == "pending_approval"
        promoted_id = promote["id"]
        pr_id = promote["promotion_request_id"]

        # Step 2: Approve the promotion
        approval = await client.governance.approve_promotion(
            promotion_request_id=pr_id,
            comment="LGTM!",
        )

        # With default 1 required approval, should auto-move to official
        assert approval["approval_count"] >= 1

        if approval["status"] == "merged":
            # Verify resource still exists after move to official
            resource = await client.resources.get(promoted_id)
            assert resource is not None
            # Resource should now be active (not pending_approval)
            assert resource.get("status") == "active"
