---
description: Design and implement E2E scenario tests using Python SDK to verify business logic and improve SDK usability
---

# E2E SDK Scenario Testing Workflow

This workflow guides the design and implementation of end-to-end tests using the Python SDK. These tests serve dual purposes:
1. **Verify System Correctness**: Test the full stack (SDK → API → Database)
2. **Validate SDK Design**: Ensure the SDK is intuitive and user-friendly

## Why SDK-Based E2E Tests?

| Aspect | Benefit |
|--------|---------|
| **Real User Experience** | Tests exactly what users will experience |
| **SDK Usability Feedback** | Awkward test code reveals awkward SDK design |
| **Full Stack Validation** | Catches integration issues between layers |
| **Living Documentation** | Tests serve as SDK usage examples |
| **NO MOCKS Policy** | Real database, real API, real behavior |

---

## Phase 1: Scenario Discovery

### 1.1 Identify Business Domain Features

Review the implemented features to identify testable scenarios:

```bash
# Check implemented resources and services
ls apps/api/services/
ls apps/api/routers/
ls libs/sdk_py/client.py
```

Map features to user workflows:

| Feature Area | User Workflow | SDK Methods |
|--------------|---------------|-------------|
| Authentication | API key management | `auth.create_api_key()`, `auth.revoke_api_key()`, `auth.get_current_user()` |
| Data Pipelines | Ingest economic data | `pipelines.submit_definition()`, `pipelines.create_instance()` |
| Experiments | Explore expressions | `experiments.create()`, `experiments.run()` |
| Signals | Register alpha signals | `signals.create()`, `signals.validate()` |
| Resources | Organize work | `resources.create()`, `resources.move()` |
| RBAC | Control access | `rbac.grant_role()`, `rbac.list_grants()` |
| Chat | Collaborate | `chat.create_channel()`, `chat.send_message()` |
| Versioning | Track changes | `refs.create_branch()`, `refs.merge()` |

### 1.2 Design Case Study Scenarios

Each case study should represent a **coherent business workflow**, not isolated operations.

**Good Scenario Design:**
```
Case Study: Quantitative Researcher Daily Workflow
1. Create a project for today's research
2. Create an expression experiment with MEAN(close, 20)
3. Run the experiment to preview results
4. If successful, save as a reusable macro
5. Register the result as a signal
6. Verify audit trail captures all actions
```

**Bad Scenario Design:**
```
# BAD: Isolated operations without business context
test_create_resource()
test_update_resource()
test_delete_resource()
```

### 1.3 Scenario Coverage Matrix

Ensure scenarios cover all dimensions:

| Dimension | Coverage Check |
|-----------|----------------|
| **CRUD Operations** | Create, Read, Update, Delete for each resource type |
| **Business Logic** | Validation rules, status transitions, guardrails |
| **Cross-Resource** | Relationships, lineage, hierarchies |
| **RBAC** | Permission checks, role inheritance |
| **Audit** | Activity emission, audit log queries |
| **Error Cases** | Invalid inputs, permission denied, not found |

## Appendix: Case Study Templates

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

---

### Template D: Authentication Workflow

```python
class TestCaseStudy_Authentication:
    """Authentication and API key management."""

    async def test_api_key_lifecycle(self, sdk_with_tenant):
        """Test full API key lifecycle: create, use, revoke."""
        client = sdk_with_tenant["client"]

        # CREATE API KEY
        result = await client.auth.create_api_key(
            name="Test Key",
            scopes=["read", "write"],
            expires_in_days=30,
        )
        assert result["key"].startswith("optaic_")
        full_key = result["key"]
        key_id = result["id"]

        # USE API KEY
        api_key_client = AsyncPlatformClient(
            base_url=client._base_url,
            api_key=full_key,
            client=AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        )

        try:
            user_info = await api_key_client.auth.get_current_user()
            assert user_info["auth_method"] == "api_key"

            # REVOKE AND VERIFY
            await client.auth.revoke_api_key(key_id)

            with pytest.raises(Exception):
                await api_key_client.auth.get_current_user()
        finally:
            await api_key_client.close()
```

---

## Output

After completing this workflow, you should have **Comprehensive E2E tests** covering all major business workflows including:
- Authentication (API keys, session login)
- Resource management
- Data pipelines
- RBAC and permissions
- Audit trails