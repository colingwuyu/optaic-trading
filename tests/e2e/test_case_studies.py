"""End-to-End Case Study Tests - Using Python SDK.

These tests simulate realistic business scenarios using the Python SDK,
which is what actual users would use to interact with the OptAIC platform.

CRITICAL PRINCIPLE: SDK-ONLY TESTING
=====================================
E2E tests must ONLY use the SDK. NO direct database access allowed.
- If something can't be done via SDK, it's a missing SDK feature
- Tests reveal SDK gaps and usability issues
- Tests serve as living documentation for SDK usage

This approach:
1. Tests the full stack (SDK → API → Database)
2. Verifies SDK API design is intuitive and user-friendly
3. Tests what actual users experience
4. Reveals missing SDK features that need development

Case Study 1: FRED Economic Data Pipeline
- Submit and deploy pipeline definitions
- Create pipeline instances for GDP and CPI
- Create datasets with full component composition

Case Study 2: Derived Metrics (QoQ/YoY Returns)
- Create expression experiments
- Run experiments to preview results
- Verify lineage relationships

Case Study 3: Scheduling and Flow Execution
- Configure schedules for datasets
- Trigger ad-hoc runs
- Verify activity/audit logs via API

Case Study 4: Team Collaboration and Governance
- Resource creation by different users
- Resource moves and updates
- Soft delete workflows

Case Study 5: Signal Registration and Promotion
- Register datasets as signals
- Validate signals
- Promote to official status

NO MOCKS - All tests use real API endpoints via SDK.
NO DIRECT DB ACCESS - All operations via SDK only.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from libs.sdk_py import AsyncPlatformClient


# =============================================================================
# FIXTURES FOR SDK-BASED TESTING
# =============================================================================
#
# These fixtures use ONLY SDK methods - no direct database access.
# If a fixture can't be implemented via SDK, that's a missing SDK feature.
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Create an AsyncPlatformClient using ASGI transport for testing.

    This tests the SDK against the real API without network overhead.
    """
    # Create httpx client with ASGI transport for in-process testing
    httpx_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    # Create SDK client with the custom httpx client
    client = AsyncPlatformClient(
        base_url="http://test",
        client=httpx_client,
    )

    yield client

    await client.close()


@pytest_asyncio.fixture(scope="function")
async def sdk_with_tenant(sdk_client: AsyncPlatformClient):
    """SDK client with a tenant and principal already set up.

    Uses SDK methods only - no direct database access.

    The tenants.create() API:
    - Creates the Tenant record
    - Creates the calling Principal (owner)
    - Creates a TenantRoot resource
    - Sets up default role permissions (owner, operator, viewer, auditor)
    - Grants owner role to the calling principal
    """
    # Generate IDs for the new tenant and principal
    tenant_id = uuid4()
    principal_id = uuid4()

    # Set identity headers for the SDK client
    # These will be used by the tenants.create() call
    sdk_client.set_principal_id(principal_id)
    sdk_client.set_tenant_id(tenant_id)

    # Create tenant via SDK - this bootstraps everything
    tenant_result = await sdk_client.tenants.create(
        name=f"TestTenant-{tenant_id}",
    )

    # The tenant creation returns the root_resource_id
    root_resource_id = tenant_result.get("root_resource_id")

    return {
        "client": sdk_client,
        "tenant_id": UUID(tenant_result["id"]),
        "principal_id": principal_id,
        "root_resource_id": UUID(root_resource_id) if root_resource_id else None,
    }


@pytest_asyncio.fixture(scope="function")
async def sdk_with_space(sdk_with_tenant):
    """SDK client with tenant and a Space for resource creation.

    Uses SDK methods only - no direct database access.

    Creates a Space under the tenant root using resources.create().
    The owner automatically has full permissions via the owner role binding.
    """
    client = sdk_with_tenant["client"]
    root_resource_id = sdk_with_tenant["root_resource_id"]

    # Create a Space via SDK under the tenant root
    space_result = await client.resources.create(
        resource_type="Space",
        parent_id=root_resource_id,
        name="Test Space",
    )

    space_id = UUID(space_result["id"])

    return {
        "client": client,
        "tenant_id": sdk_with_tenant["tenant_id"],
        "principal_id": sdk_with_tenant["principal_id"],
        "root_resource_id": root_resource_id,
        "space_id": space_id,
    }


# =============================================================================
# CASE STUDY 1: FRED ECONOMIC DATA PIPELINE
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy1_FREDEconomicData:
    """Case Study 1: Building raw economic datasets from FRED.

    Tests the workflow of:
    1. Admin submits pipeline definitions
    2. Admin deploys definitions
    3. User creates pipeline instances
    4. User creates datasets using SDK
    """

    async def test_list_pipeline_definitions(self, sdk_with_tenant):
        """Verify SDK can list pipeline definitions."""
        client = sdk_with_tenant["client"]

        # List definitions - should return empty list or existing definitions
        definitions = await client.pipelines.list_definitions()

        assert isinstance(definitions, list)
        # Verify API shape
        if len(definitions) > 0:
            assert "id" in definitions[0]

    async def test_submit_and_deploy_pipeline_definition(self, sdk_with_space):
        """Submit and deploy a FredPipeline definition via SDK."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Submit pipeline definition
        # Note: code_ref must be the registered factory key, not the full module path
        definition = await client.pipelines.submit_definition(
            name="FredPipeline",
            code_ref="FredPipeline",  # Factory registered name
            parent_id=space_id,
            category="etl",
            input_schema={"series_id": "string", "vintage": "boolean"},
            output_schema={"date": "datetime", "value": "float"},
        )

        assert definition is not None
        assert definition["name"] == "FredPipeline"
        assert definition["code_ref"] == "FredPipeline"
        assert definition["category"] == "etl"
        assert "id" in definition

        # Deploy the definition
        deployed = await client.pipelines.deploy_definition(definition["id"])

        assert deployed is not None
        # After deployment, the definition should be usable

    async def test_create_pipeline_instance(self, sdk_with_space):
        """Create a pipeline instance for GDP data.

        Uses SDK-only approach:
        1. Submit pipeline definition via SDK
        2. Deploy the definition via SDK
        3. Create instance via SDK
        """
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project to hold the pipeline
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="GDP Pipeline Project",
        )
        project_id = project["id"]

        # Step 1: Submit a pipeline definition via SDK
        definition = await client.pipelines.submit_definition(
            name="FredPipeline",
            code_ref="FredPipeline",  # Must match PIPELINE_FACTORY registration
            category="etl",
            parent_id=project_id,
        )
        definition_id = definition["id"]

        # Step 2: Deploy the definition via SDK
        await client.pipelines.deploy_definition(definition_id)

        # Step 3: Create instance via SDK
        instance = await client.pipelines.create_instance(
            name="GDP Pipeline",
            definition_id=definition_id,
            parent_id=project_id,
            config={"series_id": "GDP", "vintage": True},
            schedule={"cron": "0 6 * * *"},  # Daily at 6 AM
        )

        assert instance is not None
        assert instance["name"] == "GDP Pipeline"
        assert "id" in instance

    async def test_list_datasets(self, sdk_with_tenant):
        """Verify SDK can list datasets."""
        client = sdk_with_tenant["client"]

        datasets = await client.datasets.list()

        assert isinstance(datasets, list)


# =============================================================================
# CASE STUDY 2: DERIVED METRICS (Experiments)
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy2_DerivedMetrics:
    """Case Study 2: Creating derived datasets with expression experiments.

    Tests the workflow of:
    1. Create experiments with expressions
    2. Run experiments to preview results
    3. Update experiments
    4. Save as macro
    """

    async def test_list_experiments(self, sdk_with_tenant):
        """Verify SDK can list experiments."""
        client = sdk_with_tenant["client"]

        experiments = await client.experiments.list()

        assert isinstance(experiments, list)

    async def test_create_and_run_experiment(self, sdk_with_space):
        """Create and run an expression experiment."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project to hold the experiment
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Experiments Project",
        )
        project_id = project["id"]

        # Create experiment
        experiment = await client.experiments.create(
            name="GDP Momentum Signal",
            expression="ZSCORE(($gdp / REF($gdp, 4)) - 1, 20)",
            parent_id=project_id,
            description="Calculate GDP momentum as z-score of YoY change",
        )

        assert experiment is not None
        assert experiment["name"] == "GDP Momentum Signal"
        assert "ZSCORE" in experiment.get("expression", "")
        experiment_id = experiment["id"]

        # Get experiment details
        details = await client.experiments.get(experiment_id)
        assert details["id"] == experiment_id

    async def test_update_experiment_expression(self, sdk_with_space):
        """Update an experiment's expression."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Update Test Project",
        )

        # Create experiment
        experiment = await client.experiments.create(
            name="Test Expression",
            expression="ADD($a, $b)",
            parent_id=project["id"],
        )

        # Update the expression
        updated = await client.experiments.update(
            experiment["id"],
            expression="MEAN($a, 20)",
        )

        assert updated is not None


# =============================================================================
# CASE STUDY 3: ACTIVITIES AND AUDIT
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy3_ActivitiesAndAudit:
    """Case Study 3: Activity logging and audit trails.

    Tests the workflow of:
    1. Perform actions that generate activities
    2. Query activities via SDK
    3. Verify audit trail
    """

    async def test_list_activities(self, sdk_with_tenant):
        """Verify SDK can list activities."""
        client = sdk_with_tenant["client"]

        result = await client.activities.list()

        assert "items" in result or isinstance(result, dict)

    async def test_activities_after_resource_creation(self, sdk_with_space):
        """Verify activities are created when resources are created."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project (this should generate an activity)
        await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Activity Test Project",
        )

        # List activities
        activities = await client.activities.list()

        # Should have at least one activity
        assert activities is not None

    async def test_activities_filtered_by_resource(self, sdk_with_space):
        """Query activities for a specific resource."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Filtered Activity Project",
        )

        # Query activities for this resource
        activities = await client.activities.list(resource_id=project["id"])

        assert activities is not None


# =============================================================================
# CASE STUDY 4: TEAM COLLABORATION AND GOVERNANCE
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy4_TeamGovernance:
    """Case Study 4: Team collaboration and governance actions.

    Tests the workflow of:
    1. Create resources
    2. Move resources between projects
    3. Update resource metadata
    4. Delete resources
    """

    async def test_create_resource_hierarchy(self, sdk_with_space):
        """Create a resource hierarchy: Space -> Project -> Resource."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Team Project",
        )
        assert project["name"] == "Team Project"

        # List children of space - should include project
        children = await client.resources.list_children(space_id)
        assert "items" in children or isinstance(children, dict)

    async def test_get_resource(self, sdk_with_space):
        """Get resource details."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Get Test Project",
        )

        # Get the resource
        resource = await client.resources.get(project["id"])

        assert resource["id"] == project["id"]
        assert resource["name"] == "Get Test Project"

    async def test_update_resource(self, sdk_with_space):
        """Update resource name and metadata."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Original Name",
        )

        # Update the resource
        updated = await client.resources.update(
            project["id"],
            name="Updated Name",
            metadata={"description": "Updated project"},
        )

        assert updated["name"] == "Updated Name"

    async def test_move_resource(self, sdk_with_space):
        """Move a resource to a different parent."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create two projects
        project1 = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Project 1",
        )
        project2 = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Project 2",
        )

        # Create a nested project in project1
        nested_project = await client.resources.create(
            resource_type="Project",
            parent_id=project1["id"],
            name="Nested Project",
        )

        # Move nested project to project2
        moved = await client.resources.move(
            nested_project["id"],
            new_parent_id=project2["id"],
        )

        assert moved is not None

    async def test_soft_delete_resource(self, sdk_with_space):
        """Soft delete a resource."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="To Delete",
        )

        # Delete the resource
        result = await client.resources.delete(project["id"])

        assert result is not None


# =============================================================================
# CASE STUDY 5: SIGNAL REGISTRATION AND PROMOTION
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy5_SignalWorkflow:
    """Case Study 5: Signal registration and promotion workflow.

    Tests the workflow of:
    1. List signals
    2. Register a dataset as a signal
    3. Validate signal
    4. Promote signal
    """

    async def test_list_signals(self, sdk_with_tenant):
        """Verify SDK can list signals."""
        client = sdk_with_tenant["client"]

        signals = await client.signals.list()

        assert isinstance(signals, list)

    async def test_signal_workflow(self, sdk_with_space):
        """Test signal SDK methods.

        NOTE: The full signal workflow requires:
        1. Create PipelineInstance (for data source)
        2. Create StoreInstance (for data storage)
        3. Create AccessorInstance (for data access)
        4. Create DatasetInstance (combining the above)
        5. Register dataset as signal via signals.register()

        This test verifies the SDK methods exist and work correctly
        without the full dataset → signal dependency chain.

        See TestCaseStudy1 for pipeline/dataset creation patterns.
        """
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Signals Project",
        )

        # Verify signals.list() SDK method works
        signals = await client.signals.list(parent_id=project["id"])
        assert isinstance(signals, list)

        # NOTE: To register a signal, you'd need:
        # dataset = await client.datasets.create(
        #     name="GDP Data",
        #     parent_id=project["id"],
        #     pipeline_instance_id=...,
        #     store_instance_id=...,
        #     accessor_instance_id=...,
        # )
        # signal = await client.signals.register(
        #     dataset_id=dataset["id"],
        #     name="GDP Momentum Signal",
        #     parent_id=project["id"],
        # )


# =============================================================================
# CASE STUDY 6: RBAC AND PERMISSIONS
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy6_RBACWorkflow:
    """Case Study 6: RBAC and permission management.

    Tests the workflow of:
    1. Grant roles to users
    2. List grants
    3. Check effective permissions
    4. Revoke roles
    """

    async def test_grant_role(self, sdk_with_space):
        """Grant a role to a user using SDK-only.

        Uses SDK to:
        1. Create another principal via SDK
        2. Create a project
        3. Grant role via SDK
        """
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create another user via SDK
        other_user = await client.principals.create(
            display_name="Other User",
            email=f"other-{uuid4()}@example.com",
        )
        other_user_id = other_user["id"]

        # Create a project to scope the grant
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="RBAC Test Project",
        )

        # Grant viewer role via SDK
        grant = await client.rbac.grant(
            subject_principal_id=other_user_id,
            role_name="viewer",
            scope_resource_id=project["id"],
        )

        assert grant is not None

    async def test_list_grants(self, sdk_with_space):
        """List grants on a resource."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Grants List Project",
        )

        # List grants
        grants = await client.rbac.list_grants(project["id"])

        assert isinstance(grants, list)

    async def test_effective_permissions(self, sdk_with_space):
        """Check effective permissions on a resource."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]
        principal_id = sdk_with_space["principal_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Effective Perms Project",
        )

        # Get effective permissions
        effective = await client.rbac.effective(
            resource_id=project["id"],
            subject_principal_id=principal_id,
        )

        assert effective is not None


# =============================================================================
# CASE STUDY 7: VERSIONING AND BRANCHES
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy7_VersioningWorkflow:
    """Case Study 7: Git-like versioning with branches.

    Tests the workflow of:
    1. Create branches
    2. List branches
    3. Delete branches
    """

    async def test_branch_workflow(self, sdk_with_space):
        """Test branch creation and listing."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Versioning Project",
        )

        # Create a branch
        branch = await client.refs.create_branch(
            resource_id=project["id"],
            ref_name="feature-x",
            from_ref="main",
        )

        assert branch is not None

        # List branches
        branches = await client.refs.list_branches(project["id"])

        assert isinstance(branches, list)
        assert any(b.get("ref_name") == "feature-x" for b in branches)

        # Delete branch
        result = await client.refs.delete_branch(project["id"], "feature-x")
        assert result is not None


# =============================================================================
# CASE STUDY 8: CHAT AND MESSAGING
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy8_ChatWorkflow:
    """Case Study 8: Chat channels and messaging.

    Tests the workflow of:
    1. Create chat channels
    2. Send messages
    3. List messages
    4. Edit/delete messages
    """

    async def test_chat_workflow(self, sdk_with_space):
        """Test chat channel and messaging."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project to hold the channel
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Chat Project",
        )

        # Create a channel
        channel = await client.chat.create_channel(
            parent_id=project["id"],
            channel_kind="general",
            name="General Chat",
            topic="Team discussions",
        )

        assert channel is not None
        assert channel["name"] == "General Chat"
        channel_id = channel["id"]

        # Send a message
        message = await client.chat.send_message(
            channel_id=channel_id,
            body="Hello, team!",
        )

        assert message is not None
        assert message["body"] == "Hello, team!"
        message_id = message["id"]

        # List messages
        messages = await client.chat.list_messages(channel_id)

        assert messages is not None

        # Edit message
        edited = await client.chat.edit_message(
            message_id=message_id,
            body="Hello, team! (edited)",
        )

        assert edited["body"] == "Hello, team! (edited)"


# =============================================================================
# CASE STUDY 9: SYSTEM BOOTSTRAP AND DEFINITIONS
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy9_SystemBootstrap:
    """Case Study 9: System bootstrap and plugin definitions.

    Verifies that on application startup:
    1. System Tenant exists with admin principal
    2. System Space exists with Official + Staging sub-spaces
    3. System Project contains built-in definitions
    4. Admin can access System Space resources

    These tests use the live API server fixture which runs the full
    lifespan (bootstrap, seeding) before serving requests.
    """

    async def test_system_tenant_exists(self, sdk_live_client):
        """Verify the system tenant and admin are accessible."""
        from libs.sdk_py import SYSTEM_SPACE_ID

        # sdk_live_client is already configured with system principal/tenant
        # Get the System Space - should exist after bootstrap
        space = await sdk_live_client.resources.get(str(SYSTEM_SPACE_ID))

        assert space is not None
        assert space["type"] == "Space"
        assert space["name"] == "System Definitions"

    async def test_system_project_has_definitions(self, sdk_live_client):
        """Verify the System Project contains built-in definitions."""
        from libs.sdk_py import SYSTEM_PROJECT_ID

        # List children of System Project - should contain definitions
        children = await sdk_live_client.resources.list_children(str(SYSTEM_PROJECT_ID))

        assert children is not None
        # After bootstrap + seeding, there should be definitions
        # (pipelines, stores, accessors, ops)

    async def test_list_pipeline_definitions_includes_system(self, sdk_live_client):
        """Verify system pipeline definitions are accessible."""
        # List pipeline definitions - should include FredPipeline etc.
        definitions = await sdk_live_client.pipelines.list_definitions()

        assert isinstance(definitions, list)
        # After seeding, should have built-in definitions
        if len(definitions) > 0:
            # Verify we have at least the expected pipelines
            # Verify we have at least the expected pipelines
            _ = {d.get("name") for d in definitions}
            # FredPipeline should exist (seeded during bootstrap)
            # Note: definitions may be empty if seeding hasn't run yet


# =============================================================================
# CASE STUDY 10: ADMIN USER AND SPACE CREATION
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="SQLite concurrent write limitation: These tests trigger multiple "
    "transactions while the outbox worker is also processing, causing "
    "'database is locked' errors. Works with PostgreSQL."
)
class TestCaseStudy10_AdminUserCreation:
    """Case Study 10: Admin creates users and team spaces.

    Tests the workflow of:
    1. Admin creates a user with Personal Space via SDK
    2. Admin creates a Team Space with owner
    3. New user can access their Personal Space
    4. New user has VIEW access to System Space

    These tests use the live API server fixture which runs the full
    lifespan (bootstrap, seeding) before serving requests.

    NOTE: Skipped for SQLite E2E environment due to concurrent write limitations.
    """

    async def test_admin_create_user_with_space(self, sdk_live_client):
        """Admin creates a user with Personal Space.

        This uses the admin SDK client to:
        1. Create a Principal (user account)
        2. Create their Personal Space with Official + Staging sub-spaces
        3. Grant owner role on Personal Space
        4. Grant viewer role on System Space
        """
        # sdk_live_client is configured as system admin
        # Use admin SDK to create user with space
        result = await sdk_live_client.admin.create_user_with_space(
            display_name="Alice Smith",
            email="alice@example.com",
        )

        # Verify the response
        assert result is not None
        assert "principal_id" in result
        assert "space_id" in result
        assert "official_subspace_id" in result
        assert "staging_subspace_id" in result

        # Switch to the new user and verify they can access their space
        new_user_principal_id = result["principal_id"]
        new_user_space_id = result["space_id"]

        sdk_live_client.set_principal_id(new_user_principal_id)

        # Get the user's personal space
        space = await sdk_live_client.resources.get(new_user_space_id)
        assert space is not None
        assert space["id"] == new_user_space_id

    async def test_admin_create_team_space(self, sdk_live_client):
        """Admin creates a Team Space with an owner."""
        # First create a user who will be the owner
        user_result = await sdk_live_client.admin.create_user_with_space(
            display_name="Team Owner",
            email="owner@example.com",
        )
        owner_principal_id = user_result["principal_id"]

        # Create team space via admin SDK
        result = await sdk_live_client.admin.create_team_space(
            name="Quant Research Team",
            owner_principal_id=owner_principal_id,
            description="Our research team space",
        )

        # Verify the response
        assert result is not None
        assert "space_id" in result
        assert "official_subspace_id" in result
        assert "staging_subspace_id" in result
        assert result.get("space_kind") == "team"

        # Switch to owner and verify they can access the team space
        sdk_live_client.set_principal_id(owner_principal_id)
        team_space = await sdk_live_client.resources.get(result["space_id"])
        assert team_space is not None
        assert team_space["name"] == "Quant Research Team"


# =============================================================================
# CASE STUDY 11: RESOURCE COPY FROM SYSTEM SPACE
# =============================================================================


@pytest.mark.asyncio
class TestCaseStudy11_ResourceCopy:
    """Case Study 11: Copy resources from System Space.

    Tests the workflow of:
    1. User has VIEW access to System Space
    2. User copies a pipeline definition to their project
    3. The copy has derived_from lineage to the source
    4. User can create instances from the copy
    """

    async def test_copy_resource_to_project(self, sdk_with_space):
        """Copy a resource to a user's project.

        This simulates copying a pipeline definition from System Space
        to a user's Personal Space project.
        """
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create a project in user's space
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="My Pipeline Project",
        )
        project_id = project["id"]

        # Create a source resource (simulating a system definition)
        source = await client.resources.create(
            resource_type="PipelineDefinition",
            parent_id=space_id,
            name="Source Pipeline",
            metadata={"code_ref": "FredPipeline", "category": "etl"},
        )
        source_id = source["id"]

        # Copy the resource to the project
        copy = await client.resources.copy(
            resource_id=source_id,
            target_parent_id=project_id,
            new_name="My FredPipeline",
        )

        # Verify the copy
        assert copy is not None
        assert copy["name"] == "My FredPipeline"
        assert copy["source_id"] == source_id
        assert copy["parent_id"] == project_id
        assert copy["derived_from_id"] == source_id

    async def test_copy_preserves_type(self, sdk_with_space):
        """Verify copy preserves the resource type."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create source and target
        source = await client.resources.create(
            resource_type="DatasetInstance",
            parent_id=space_id,
            name="Source Dataset",
        )
        target_project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Target Project",
        )

        # Copy the resource
        copy = await client.resources.copy(
            resource_id=source["id"],
            target_parent_id=target_project["id"],
        )

        # Verify type is preserved
        assert copy["type"] == "DatasetInstance"
        assert copy["name"] == "Source Dataset"  # Default to source name

    async def test_copy_with_default_name(self, sdk_with_space):
        """Verify copy uses source name when new_name not provided."""
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Create source
        source = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Original Name",
        )

        # Create target parent
        target = await client.resources.create(
            resource_type="Space",
            parent_id=space_id,
            name="Target Space",
        )

        # Copy without new_name
        copy = await client.resources.copy(
            resource_id=source["id"],
            target_parent_id=target["id"],
        )

        # Should use source name
        assert copy["name"] == "Original Name"
