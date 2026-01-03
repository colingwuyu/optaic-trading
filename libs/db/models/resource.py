from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import List, Optional
from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from ..types import JSONType, UUIDArrayType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    type: Mapped[str] = mapped_column(String(100), index=True)
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("resources.id"), nullable=True, index=True
    )
    owner_principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("principals.id"), index=True
    )
    space_kind: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # personal|team|system
    subspace_kind: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # official|staging|custom
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(50), default="active"
    )  # active|archived|deleted
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_resources_tenant_parent", "tenant_id", "parent_id"),
        Index("ix_resources_tenant_type", "tenant_id", "type"),
        Index("ix_resources_tenant_owner", "tenant_id", "owner_principal_id"),
    )


class ResourceEdge(Base):
    __tablename__ = "resource_edges"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    src_resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True, index=True
    )
    dst_resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True, index=True
    )
    edge_type: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )  # contains|composes|references|...
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        Index("ix_resource_edges_tenant_src", "tenant_id", "src_resource_id"),
        Index("ix_resource_edges_tenant_dst", "tenant_id", "dst_resource_id"),
    )


class ResourceVersion(Base):
    __tablename__ = "resource_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("resources.id"), index=True)
    parents: Mapped[List[UUID]] = mapped_column(UUIDArrayType(), default=list)
    content: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    content_ref: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    __table_args__ = (
        Index(
            "ix_resource_versions_tenant_res_created",
            "tenant_id",
            "resource_id",
            "created_at",
        ),
    )


class ResourceRef(Base):
    __tablename__ = "resource_refs"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(
        ForeignKey("resources.id"), primary_key=True, index=True
    )
    ref_name: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )  # main, staging, etc.
    head_version_id: Mapped[UUID] = mapped_column(ForeignKey("resource_versions.id"))
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("principals.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
