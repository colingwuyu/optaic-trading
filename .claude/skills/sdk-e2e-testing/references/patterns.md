# E2E SDK Test Patterns

## Writing Scenario Tests

### Test Structure Pattern

Each test should follow the **User Story Pattern**:

```python
class TestCaseStudy_QuantResearchWorkflow:
    """Case Study: Quantitative Researcher builds and validates a signal.

    Persona: Quant researcher exploring alpha ideas
    Goal: Create, test, and register a new signal
    Success: Signal is validated and ready for promotion
    """

    async def test_full_research_workflow(self, sdk_with_space):
        """
        Scenario: Researcher creates and validates a momentum signal

        Given: A researcher with a project space
        When: They create an experiment, run it, and register as signal
        Then: The signal is validated with full audit trail
        """
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Step 1: Create a project for this research
        project = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Momentum Signal Research",
        )
        assert project["name"] == "Momentum Signal Research"
        project_id = project["id"]

        # Step 2: Create an expression experiment
        experiment = await client.experiments.create(
            parent_id=project_id,
            name="20-day Momentum",
            expression="MEAN(close, 20) / LAG(MEAN(close, 20), 5) - 1",
        )
        assert "id" in experiment
        assert experiment["expression"] == "MEAN(close, 20) / LAG(MEAN(close, 20), 5) - 1"

        # Step 3: Run the experiment (preview results)
        # Note: In real scenario, would pass actual data context
        run_result = await client.experiments.run(
            experiment_id=experiment["id"],
            context={},  # Empty for this test
        )
        # Verify run completed (may succeed or fail based on data)
        assert "success" in run_result

        # Step 4: Register as a signal
        signal = await client.signals.create(
            parent_id=project_id,
            name="Momentum_20d",
            description="20-day momentum signal",
        )
        assert signal["name"] == "Momentum_20d"

        # Step 5: Verify audit trail
        activities = await client.activities.list(
            resource_id=project_id,
            limit=50,
        )
        actions = [a["action"] for a in activities]
        # Should see: resource created, experiment created, signal created
        assert len(activities) >= 3
```

### SDK Usability Assessment Checklist

While writing tests, evaluate SDK usability:

| Criterion | Question | Red Flag |
|-----------|----------|----------|
| **Discoverability** | Can I find the method I need? | Method buried in unexpected location |
| **Naming** | Does the method name match my mental model? | `submit_definition` vs `create_pipeline` confusion |
| **Parameters** | Are required params obvious? | Too many required params, unclear names |
| **Response** | Does the response include what I need? | Missing `id`, `name`, or other key fields |
| **Error Messages** | Do errors explain what went wrong? | Generic "400 Bad Request" |
| **Consistency** | Similar operations work similarly? | `create()` vs `submit()` vs `add()` |

**Document SDK Issues:**
```python
# TODO(SDK-USABILITY): Response should include 'name' field
# Currently returns: {"id": "...", "status": "created"}
# User expects: {"id": "...", "name": "...", "status": "created"}
channel = await client.chat.create_channel(...)
# WORKAROUND: Must fetch separately to get name
```

### Error Case Testing

Include negative scenarios:

```python
async def test_permission_denied_scenarios(self, sdk_with_space):
    """Verify proper error handling for unauthorized operations."""
    client = sdk_with_space["client"]

    # Create a second user without permissions
    other_user_id = uuid4()
    # ... setup other user ...

    # Attempt operation without permission
    with pytest.raises(PermissionError) as exc_info:
        await client.resources.delete(
            resource_id=some_resource_id,
            principal_id=other_user_id,  # No delete permission
        )

    assert "403" in str(exc_info.value) or "permission" in str(exc_info.value).lower()


async def test_validation_error_messages(self, sdk_with_space):
    """Verify validation errors are clear and actionable."""
    client = sdk_with_space["client"]

    # Invalid expression syntax
    with pytest.raises(ValueError) as exc_info:
        await client.experiments.create(
            parent_id=sdk_with_space["space_id"],
            name="Bad Experiment",
            expression="INVALID_FUNC(x, y)",  # Unknown function
        )

    error_msg = str(exc_info.value)
    # Error should mention the unknown function
    assert "INVALID_FUNC" in error_msg or "unknown" in error_msg.lower()
```

## Case Study Templates

### Template A: CRUD Workflow

```python
class TestCaseStudy_ResourceManagement:
    """Basic resource lifecycle testing."""

    async def test_create_read_update_delete(self, sdk_with_space):
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # CREATE
        resource = await client.resources.create(
            resource_type="Project",
            parent_id=space_id,
            name="Test Project",
        )
        assert resource["id"]
        resource_id = resource["id"]

        # READ
        fetched = await client.resources.get(resource_id)
        assert fetched["name"] == "Test Project"

        # UPDATE
        updated = await client.resources.update(
            resource_id=resource_id,
            name="Updated Project",
        )
        assert updated["name"] == "Updated Project"

        # DELETE (soft)
        await client.resources.delete(resource_id)
        deleted = await client.resources.get(resource_id)
        assert deleted["status"] == "deleted"
```

### Template B: Multi-User Workflow

```python
class TestCaseStudy_TeamCollaboration:
    """Tests involving multiple users with different permissions."""

    async def test_owner_and_viewer_permissions(self, test_engine, sdk_client):
        # Setup: Create two users
        owner_id, viewer_id = uuid4(), uuid4()
        # ... setup both users ...

        # Owner creates resource
        owner_client = sdk_client.with_principal(owner_id)
        project = await owner_client.resources.create(...)

        # Viewer can read but not modify
        viewer_client = sdk_client.with_principal(viewer_id)
        # Grant viewer role...

        fetched = await viewer_client.resources.get(project["id"])
        assert fetched  # Can read

        with pytest.raises(PermissionError):
            await viewer_client.resources.delete(project["id"])  # Cannot delete
```

### Template C: Audit Trail Verification

```python
class TestCaseStudy_AuditCompliance:
    """Verify all operations are properly audited."""

    async def test_operations_create_audit_trail(self, sdk_with_space):
        client = sdk_with_space["client"]
        space_id = sdk_with_space["space_id"]

        # Perform operations
        project = await client.resources.create(...)
        await client.resources.update(resource_id=project["id"], name="New Name")

        # Query audit log
        activities = await client.activities.list(
            resource_id=project["id"],
        )

        actions = [a["action"] for a in activities]
        assert "resource.created" in actions
        assert "resource.updated" in actions

        # Verify payload contains relevant details
        create_activity = next(a for a in activities if a["action"] == "resource.created")
        assert create_activity["payload"]["name"] == project["name"]
```
