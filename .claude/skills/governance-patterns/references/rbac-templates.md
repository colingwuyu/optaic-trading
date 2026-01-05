# RBAC Templates

Templates define role binding mutations applied during governance operations.

## Template Structure

```python
from libs.db.models.promotion import RbacTemplate

template = RbacTemplate(
    id=uuid4(),
    tenant_id=tenant_id,
    name="branch",  # Unique per tenant
    policy={
        "bindings": [
            {"principal": "actor_id", "role": "owner"},
            {"principal": "source_owner_id", "role": "viewer"},
        ],
        "revocations": [
            {"principal": "old_owner_id", "role": "owner"},
        ]
    }
)
```

## Context Variables

Templates use variable substitution for principals:

| Variable | Description |
|----------|-------------|
| `actor_id` | User performing the operation |
| `source_owner_id` | Original owner of source resource |
| `target_owner_id` | New owner (for transfer) |
| `team_id` | Team principal (for promote) |
| `previous_owner_id` | Previous owner (for transfer) |

## Built-in Templates

### Branch Template

Creates personal fork with viewer access for original owner.

```python
{
    "name": "branch",
    "policy": {
        "bindings": [
            {"principal": "actor_id", "role": "owner"},
            {"principal": "source_owner_id", "role": "viewer"}
        ]
    }
}
```

### Transfer Template

Transfers ownership, demotes previous owner to viewer.

```python
{
    "name": "transfer",
    "policy": {
        "bindings": [
            {"principal": "target_owner_id", "role": "owner"},
            {"principal": "previous_owner_id", "role": "viewer"}
        ],
        "revocations": [
            {"principal": "previous_owner_id", "role": "owner"}
        ]
    }
}
```

### Promote Template

Promotes to team with delegator role for promoter.

```python
{
    "name": "promote",
    "policy": {
        "bindings": [
            {"principal": "team_id", "role": "owner"},
            {"principal": "actor_id", "role": "delegator"}
        ]
    }
}
```

## Applying Templates

```python
service = GovernanceService()

# Get template by name
template = await service.get_rbac_template(session, tenant_id, "branch")

# Apply with context
context = {
    "actor_id": actor.id,
    "source_owner_id": source.owner_principal_id,
}

bindings = await service.apply_rbac_template(
    session, tenant_id, resource_id, template, context
)
```

## Custom Templates

Create tenant-specific templates for custom workflows:

```python
# Two-level approval template
await service.create_rbac_template(
    session, actor,
    name="two_level_promote",
    policy={
        "bindings": [
            {"principal": "team_id", "role": "owner"},
            {"principal": "actor_id", "role": "reviewer"},
            {"principal": "approver_1_id", "role": "approver"},
            {"principal": "approver_2_id", "role": "approver"},
        ]
    }
)
```

## Role Hierarchy

Standard roles in order of decreasing privilege:

1. **owner** - Full control, can delete, transfer
2. **admin** - Manage settings, users, but not delete
3. **delegator** - Can grant roles to others
4. **editor** - Can modify content
5. **reviewer** - Can approve/reject
6. **viewer** - Read-only access

## Template Validation

Templates are validated on creation:

- `bindings` and `revocations` are optional arrays
- Each entry must have `principal` (variable name)
- Each entry should have `role` (role name)
- Unknown variables are logged as warnings

```python
# Template policy schema
{
    "bindings": [
        {"principal": str, "role": str}
    ],
    "revocations": [
        {"principal": str, "role": str | None}  # None revokes all roles
    ]
}
```
