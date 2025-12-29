from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import String, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from ..types import JSONType

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class RoleBinding(Base):
    __tablename__ = "role_bindings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    scope_resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    role_name: Mapped[str] = mapped_column(String(100))
    conditions: Mapped[dict] = mapped_column(JSONType, default=dict)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_role_bindings_tenant_principal_active",
            "tenant_id",
            "principal_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_role_bindings_tenant_scope_active",
            "tenant_id",
            "scope_resource_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

class RolePermission(Base):
    __tablename__ = "role_permissions"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    role_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    perm_name: Mapped[str] = mapped_column(String(100), primary_key=True)
