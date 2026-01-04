# Multi-Account Sandbox Testing Patterns

Patterns for testing with the multi-account sandbox infrastructure.

## Overview

The sandbox provides realistic multi-tenant environments for testing RBAC, audit logging, lineage, and domain logic. All tests use real database sessions with ORM models.

## Fixtures

### sandbox_env

Creates two tenants (Alpha and Beta) with full user hierarchies:

```python
@pytest.mark.asyncio
async def test_multi_tenant(db_session, sandbox_env):
    """Test using multi-tenant sandbox."""
    alpha = sandbox_env.tenant_alpha  # SandboxTenant
    beta = sandbox_env.tenant_beta    # SandboxTenant
    external = sandbox_env.external_user  # SandboxUser with no access
```

### sandbox_with_resources

Extends sandbox_env with pre-created projects and datasets:

```python
@pytest.mark.asyncio
async def test_with_resources(db_session, sandbox_with_resources):
    """Test with pre-created resource hierarchy."""
    alpha = sandbox_with_resources.tenant_alpha
    # Each tenant has:
    # - 1 root space
    # - 2 projects under the space
    # - 2 datasets under each project
```

### Actor Context Fixtures

```python
@pytest.mark.asyncio
async def test_rbac(alpha_admin_actor, alpha_analyst_actor, alpha_viewer_actor):
    """Test with pre-built ActorContext objects."""
    assert alpha_admin_actor.traits["role"] == "admin"
    assert alpha_analyst_actor.traits["role"] == "analyst"
```

## Sandbox Data Classes

### SandboxUser

```python
@dataclass
class SandboxUser:
    id: UUID
    tenant_id: UUID
    display_name: str
    email: str
    role: str  # admin, analyst, viewer

    def to_actor(self) -> ActorContext:
        """Create ActorContext for this user."""
```

### SandboxTenant

```python
@dataclass
class SandboxTenant:
    id: UUID
    name: str
    admin: SandboxUser
    analysts: list[SandboxUser]  # Default: 2 analysts
    viewers: list[SandboxUser]   # Default: 1 viewer
    spaces: list[UUID]           # Root team spaces

    @property
    def all_users(self) -> list[SandboxUser]:
        """Get all users in this tenant."""
```

## Helper Functions

### create_resource

Creates a resource with proper ORM handling:

```python
resource_id = await create_resource(
    db_session,
    tenant_id=alpha.id,
    owner_principal_id=alpha.admin.id,
    resource_type="DatasetInstance",
    name="Test Dataset",
    parent_id=space_id,  # Optional
    space_kind="team",   # Optional: for Space resources
)
```

### create_role_binding

Creates RBAC role bindings:

```python
binding_id = await create_role_binding(
    db_session,
    tenant_id=alpha.id,
    principal_id=user.id,
    scope_resource_id=space_id,
    role_name="analyst",  # admin, analyst, viewer
    granted_by=admin.id,
)
```

### create_activity

Creates activity records with proper visibility:

```python
activity_id = await create_activity(
    db_session,
    tenant_id=alpha.id,
    actor_principal_id=admin.id,
    resource_id=space_id,
    resource_type="Space",
    action="resource.created",
    payload={"key": "value"},
    visibility="resource",  # private, resource, tenant
)
```

### create_lineage_edge

Creates lineage relationships:

```python
await create_lineage_edge(
    db_session,
    tenant_id=alpha.id,
    upstream_id=source_dataset_id,
    downstream_id=derived_dataset_id,
    edge_kind="data_dependency",  # or "schema_dependency"
)
```

## RBAC Testing Patterns

### Cross-Tenant Isolation

```python
@pytest.mark.asyncio
async def test_tenant_cannot_see_other_tenant_resources(
    db_session,
    sandbox_env,
):
    """Verify strict tenant isolation."""
    alpha = sandbox_env.tenant_alpha
    beta = sandbox_env.tenant_beta

    # Create resource in Alpha
    resource_id = await create_resource(
        db_session, alpha.id, alpha.admin.id,
        "DatasetInstance", "Alpha Private Data",
        parent_id=alpha.spaces[0],
    )

    # Query as Beta - should NOT see Alpha's resources
    stmt = select(Resource).where(Resource.tenant_id == beta.id)
    result = await db_session.execute(stmt)
    beta_resources = result.scalars().all()

    assert resource_id not in [r.id for r in beta_resources]
```

### Role-Based Permissions

```python
@pytest.mark.asyncio
async def test_role_permissions_enforced(
    db_session,
    sandbox_env,
):
    """Verify role-based access control."""
    alpha = sandbox_env.tenant_alpha

    # Admin has all permissions
    admin_bindings = await get_role_bindings(db_session, alpha.admin.id)
    assert any(b.role_name == "admin" for b in admin_bindings)

    # Analyst has limited permissions
    analyst_bindings = await get_role_bindings(db_session, alpha.analysts[0].id)
    assert any(b.role_name == "analyst" for b in analyst_bindings)
```

### Hierarchy Inheritance

```python
@pytest.mark.asyncio
async def test_rbac_inheritance(db_session, sandbox_env):
    """Test RBAC role inheritance through resource hierarchy."""
    alpha = sandbox_env.tenant_alpha

    # Create project under space (user has role on space)
    project_id = await create_resource(
        db_session, alpha.id, alpha.admin.id,
        "Project", "Child Project",
        parent_id=alpha.spaces[0],  # Inherits roles from space
    )

    # Analyst should have access to project via inherited role
    # (their role on space applies to child project)
```

## Audit Log Testing Patterns

### Activity Creation

```python
@pytest.mark.asyncio
async def test_activity_with_all_fields(db_session, sandbox_env):
    """Test activity record has all required fields."""
    alpha = sandbox_env.tenant_alpha

    activity_id = await create_activity(
        db_session,
        alpha.id,
        alpha.admin.id,
        alpha.spaces[0],
        "Space",
        "space.updated",
        payload={"change": "description"},
    )

    activity = await db_session.get(Activity, activity_id)
    assert activity.tenant_id == alpha.id
    assert activity.actor_principal_id == alpha.admin.id
    assert activity.correlation_id is not None
    assert activity.created_at is not None
```

### Visibility Scoping

```python
@pytest.mark.asyncio
async def test_activity_visibility(db_session, sandbox_env):
    """Test activity visibility levels."""
    alpha = sandbox_env.tenant_alpha

    # Create activities with different visibility
    for visibility in ["private", "resource", "tenant"]:
        activity = Activity(
            id=uuid4(),
            tenant_id=alpha.id,
            actor_principal_id=alpha.admin.id,
            resource_id=alpha.spaces[0],
            resource_type="Space",
            action=f"{visibility}.test",
            visibility=visibility,
            payload={},
        )
        db_session.add(activity)

    await db_session.flush()

    # Query tenant-visible only
    stmt = select(Activity).where(
        Activity.tenant_id == alpha.id,
        Activity.visibility == "tenant",
    )
    result = await db_session.execute(stmt)
    assert all(a.visibility == "tenant" for a in result.scalars().all())
```

## Lineage Testing Patterns

### Dependency Resolution

```python
@pytest.mark.asyncio
async def test_lineage_resolution(db_session, sandbox_env):
    """Test LineageResolver dependency resolution."""
    from libs.orchestration.lineage import LineageResolver

    alpha = sandbox_env.tenant_alpha
    space_id = alpha.spaces[0]

    # Create A -> B -> C chain
    a = await create_dataset_instance(db_session, alpha.id, alpha.admin.id, "A", space_id)
    b = await create_dataset_instance(db_session, alpha.id, alpha.admin.id, "B", space_id)
    c = await create_dataset_instance(db_session, alpha.id, alpha.admin.id, "C", space_id)

    await create_lineage_edge(db_session, alpha.id, a, b)
    await create_lineage_edge(db_session, alpha.id, b, c)

    resolver = LineageResolver()

    # Direct upstreams of C: [B]
    direct = await resolver.resolve_upstream_dependencies(
        db_session, c, recursive=False
    )
    assert b in direct
    assert a not in direct

    # All ancestors of C: [A, B]
    all_ancestors = await resolver.resolve_upstream_dependencies(
        db_session, c, recursive=True
    )
    assert a in all_ancestors
    assert b in all_ancestors
```

### Diamond Pattern

```python
@pytest.mark.asyncio
async def test_diamond_pattern(db_session, sandbox_env):
    """Test handling of diamond dependencies (A -> B, C -> D)."""
    # A
    # |\
    # B C
    # |/
    # D

    # ... create datasets and edges ...

    resolver = LineageResolver()
    ancestors = await resolver.resolve_upstream_dependencies(
        db_session, dataset_d, recursive=True
    )

    # Use set for comparison - resolver may return duplicates
    ancestor_set = set(ancestors)
    assert dataset_a in ancestor_set
    assert dataset_b in ancestor_set
    assert dataset_c in ancestor_set
```

## Important Notes

### ORM-Only Data Creation

**CRITICAL:** Always use ORM models for creating test data, not raw SQL.

```python
# CORRECT: ORM model
resource = Resource(
    id=uuid.uuid4(),
    tenant_id=tenant_id,
    owner_principal_id=principal_id,
    type="DatasetInstance",
    name="Test",
    status="active",
)
db_session.add(resource)
await db_session.flush()

# WRONG: Raw SQL (UUID handling issues with SQLite)
await db_session.execute(
    text("INSERT INTO resources ..."),
    {"id": str(uuid.uuid4()), ...}  # String UUIDs won't match ORM queries
)
```

### Session Identity Caching

SQLAlchemy caches objects by primary key. When testing updates:

```python
# The resolver's session.get() returns the same object instance
instance = await db_session.get(DatasetInstance, resource_id)
instance.upstream_resource_ids = [upstream_id]
await db_session.flush()

# Later, resolver.update_upstream_status() modifies the SAME instance
all_ready = await resolver.update_upstream_status(
    db_session, resource_id, upstream_id, "ready"
)

# No refresh needed - instance is already updated in memory
assert instance.upstream_status[str(upstream_id)] == "ready"
```

### Timezone Handling

When comparing datetime fields, normalize timezones:

```python
# Normalize for comparison
if dt.tzinfo is not None:
    dt = dt.replace(tzinfo=None)
```
