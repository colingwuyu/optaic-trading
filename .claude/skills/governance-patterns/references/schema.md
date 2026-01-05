# Governance Schema

## Resource Table Extensions

The `resources` table includes governance columns:

```sql
-- artifact_ref: UUID reference to artifact folder
-- Path: {DATA_DIR}/artifacts/{artifact_ref}/
artifact_ref UUID NULL

-- Indexed for quick artifact lookup
CREATE INDEX ix_resources_artifact_ref ON resources(artifact_ref);
```

## ResourceEdge Table Extensions

The `resource_edges` table tracks lineage:

```sql
-- Composite primary key
PRIMARY KEY (tenant_id, src_resource_id, dst_resource_id, edge_type)

-- Who created this edge (for audit trail)
created_by_principal_id UUID REFERENCES principals(id)

-- Indexed for quick lineage queries
CREATE INDEX ix_resource_edges_created_by ON resource_edges(created_by_principal_id);
```

### Edge Direction Convention

For lineage edges:
- `src_resource_id`: The derived/new resource
- `dst_resource_id`: The source/original resource

Example: If resource B is branched from resource A:
- src_resource_id = B (the branch)
- dst_resource_id = A (the source)
- edge_type = "branch_of"

## Governance Edge Types

| Edge Type | Description | Src | Dst |
|-----------|-------------|-----|-----|
| `copy_of` | Reference copy | Copy | Original |
| `branch_of` | Branch with files | Branch | Source |
| `transferred_from` | Ownership transfer | Resource | Resource (self) |
| `promoted_from` | Promoted to team | Promoted | Personal |
| `merged_from` | Merged branch | Target | Branch |
| `derived_from` | General derivation | Derived | Source |

## Migration

Migration `j3d4e5f6g7h8_artifact_governance_columns.py`:

```python
def upgrade() -> None:
    # Add artifact_ref to resources
    op.add_column("resources", sa.Column("artifact_ref", sa.Uuid(), nullable=True))
    op.create_index("ix_resources_artifact_ref", "resources", ["artifact_ref"])

    # Add created_by to resource_edges
    op.add_column("resource_edges", sa.Column(
        "created_by_principal_id", sa.Uuid(),
        sa.ForeignKey("principals.id"), nullable=True
    ))
    op.create_index("ix_resource_edges_created_by", "resource_edges", ["created_by_principal_id"])
```

## ORM Models

```python
# libs/db/models/resource.py

class Resource(Base):
    # ... existing columns ...
    artifact_ref: Mapped[Optional[UUID]] = mapped_column(nullable=True, index=True)

class ResourceEdge(Base):
    # ... existing columns ...
    created_by_principal_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("principals.id"), nullable=True, index=True
    )
```
