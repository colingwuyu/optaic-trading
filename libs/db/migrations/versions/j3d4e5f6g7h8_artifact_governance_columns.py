"""Add artifact_ref and governance lineage columns.

Adds columns for artifact management and governance lineage:
- artifact_ref on resources: UUID reference to artifact folder
- created_by_principal_id on resource_edges: tracks who created the edge

These support the governance operations:
- Copy (reference): Same artifact_ref, no new edge
- Branch: New artifact_ref (copied files), branch_of edge
- Transfer: Same artifact_ref, transferred_from edge
- Promote: New artifact_ref (copied files), promoted_from edge
- Merge: Artifact replaces ancestor, merged_from edge

Revision ID: j3d4e5f6g7h8
Revises: i2c3d4e5f6g7
Create Date: 2026-01-04 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j3d4e5f6g7h8"
down_revision: str | None = "i2c3d4e5f6g7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add artifact_ref column to resources table
    # This is a UUID that references the artifact folder path:
    # {DATA_DIR}/artifacts/{artifact_ref}/
    op.add_column(
        "resources",
        sa.Column("artifact_ref", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_resources_artifact_ref",
        "resources",
        ["artifact_ref"],
        unique=False,
    )

    # Add created_by_principal_id column to resource_edges table
    # This tracks who created the lineage edge (branch, promote, merge, etc.)
    # Note: SQLite doesn't support adding FK constraints with ALTER, so we add
    # the column without the constraint. The FK relationship is documented but
    # not enforced at DB level for SQLite (Postgres gets proper FKs via model).
    op.add_column(
        "resource_edges",
        sa.Column(
            "created_by_principal_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_resource_edges_created_by",
        "resource_edges",
        ["created_by_principal_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_resource_edges_created_by", table_name="resource_edges")
    op.drop_column("resource_edges", "created_by_principal_id")

    op.drop_index("ix_resources_artifact_ref", table_name="resources")
    op.drop_column("resources", "artifact_ref")
