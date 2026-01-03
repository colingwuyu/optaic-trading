"""Add unique constraint for activity correlation id

Revision ID: 6f3d2b4c9a7e
Revises: e1add04204b8
Create Date: 2025-12-25 00:32:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f3d2b4c9a7e"
down_revision: Union[str, Sequence[str], None] = "e1add04204b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("activities") as batch_op:
            batch_op.create_unique_constraint(
                "uq_activities_tenant_correlation",
                ["tenant_id", "correlation_id"],
            )
    else:
        op.create_unique_constraint(
            "uq_activities_tenant_correlation",
            "activities",
            ["tenant_id", "correlation_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("activities") as batch_op:
            batch_op.drop_constraint(
                "uq_activities_tenant_correlation",
                type_="unique",
            )
    else:
        op.drop_constraint(
            "uq_activities_tenant_correlation",
            "activities",
            type_="unique",
        )
