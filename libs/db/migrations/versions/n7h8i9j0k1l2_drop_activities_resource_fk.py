"""Drop activities.resource_id foreign key constraint.

The activities table can track activities for non-resource entities like
ValidationReport. The FK constraint to resources.id is incorrect and was
added by mistake in the initial migration. The Activity model correctly
defines resource_id without a ForeignKey constraint.

Revision ID: n7h8i9j0k1l2
Revises: m6g7h8i9j0k1
Create Date: 2026-01-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "n7h8i9j0k1l2"
down_revision: str | None = "m6g7h8i9j0k1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the incorrect FK constraint on activities.resource_id.

    SQLite doesn't support ALTER TABLE DROP CONSTRAINT, so we use the
    table-rebuild pattern: create new table, copy data, drop old, rename.
    """
    # First check if the new table already exists (from a failed migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "activities_new" in tables:
        op.drop_table("activities_new")

    # Create new table without the resource_id FK
    op.create_table(
        "activities_new",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.Uuid(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_principal_id", sa.Uuid(), nullable=True),
        sa.Column("visibility", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("authz_decision", sa.String(length=50), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Keep FKs to principals and tenants, but NOT to resources
        sa.ForeignKeyConstraint(
            ["actor_principal_id"],
            ["principals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_principal_id"],
            ["principals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        # Add the unique constraint during table creation
        sa.UniqueConstraint(
            "tenant_id",
            "correlation_id",
            "action",
            "resource_id",
            name="uq_activities_tenant_correlation_action_resource",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Copy data from old table
    op.execute("""
        INSERT INTO activities_new (
            id, tenant_id, actor_principal_id, resource_id, resource_type,
            action, target_principal_id, visibility, payload, authz_decision,
            correlation_id, created_at
        )
        SELECT
            id, tenant_id, actor_principal_id, resource_id, resource_type,
            action, target_principal_id, visibility, payload, authz_decision,
            correlation_id, created_at
        FROM activities
    """)

    # Drop old table
    op.drop_table("activities")

    # Rename new table
    op.rename_table("activities_new", "activities")

    # Recreate indexes
    op.create_index(
        "ix_activities_resource_id",
        "activities",
        ["resource_id"],
        unique=False,
    )


def downgrade() -> None:
    """Re-add the FK constraint (not recommended)."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "activities_old" in tables:
        op.drop_table("activities_old")

    # Create new table with the FK
    op.create_table(
        "activities_old",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_principal_id", sa.Uuid(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_principal_id", sa.Uuid(), nullable=True),
        sa.Column("visibility", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("authz_decision", sa.String(length=50), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_principal_id"],
            ["principals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_principal_id"],
            ["principals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "correlation_id",
            "action",
            "resource_id",
            name="uq_activities_tenant_correlation_action_resource",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Note: Downgrade will fail if there are activities referencing
    # non-existent resources. This is expected behavior.
    op.execute("""
        INSERT INTO activities_old (
            id, tenant_id, actor_principal_id, resource_id, resource_type,
            action, target_principal_id, visibility, payload, authz_decision,
            correlation_id, created_at
        )
        SELECT
            id, tenant_id, actor_principal_id, resource_id, resource_type,
            action, target_principal_id, visibility, payload, authz_decision,
            correlation_id, created_at
        FROM activities
    """)

    op.drop_table("activities")
    op.rename_table("activities_old", "activities")

    op.create_index(
        "ix_activities_resource_id",
        "activities",
        ["resource_id"],
        unique=False,
    )
