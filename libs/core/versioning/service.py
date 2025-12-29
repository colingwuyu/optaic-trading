from __future__ import annotations

from typing import Dict, Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.db.models.resource import Resource, ResourceRef, ResourceVersion

from .registry import default_content, is_versioned_type, serialize_content


async def get_current_head(
    session: AsyncSession, resource_id: UUID, ref_name: str = "main"
) -> Optional[ResourceVersion]:
    result = await session.execute(
        select(ResourceVersion)
        .join(ResourceRef, ResourceRef.head_version_id == ResourceVersion.id)
        .where(
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == ref_name,
        )
    )
    return result.scalars().first()


async def create_version(
    session: AsyncSession,
    resource_id: UUID,
    parents: Iterable[UUID],
    content: Dict[str, object],
    created_by: UUID,
    version_id: Optional[UUID] = None,
) -> ResourceVersion:
    result = await session.scalars(select(Resource).where(Resource.id == resource_id))
    resource = result.first()
    if not resource:
        raise ValueError("Resource not found for versioning")
    if not is_versioned_type(resource.type):
        raise ValueError(f"Resource type '{resource.type}' is not versioned")

    serialized = serialize_content(resource.type, content)
    version = ResourceVersion(
        id=version_id,
        tenant_id=resource.tenant_id,
        resource_id=resource_id,
        parents=list(parents),
        content=serialized,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return version


async def update_ref(
    session: AsyncSession,
    resource_id: UUID,
    ref_name: str,
    head_version_id: UUID,
    updated_by: UUID,
) -> ResourceRef:
    result = await session.scalars(
        select(ResourceRef).where(
            ResourceRef.resource_id == resource_id,
            ResourceRef.ref_name == ref_name,
        )
    )
    ref = result.first()
    if ref:
        ref.head_version_id = head_version_id
        ref.updated_by = updated_by
        await session.flush()
        return ref

    resource_result = await session.scalars(
        select(Resource).where(Resource.id == resource_id)
    )
    resource = resource_result.first()
    if not resource:
        raise ValueError("Resource not found for ref update")

    ref = ResourceRef(
        tenant_id=resource.tenant_id,
        resource_id=resource_id,
        ref_name=ref_name,
        head_version_id=head_version_id,
        updated_by=updated_by,
    )
    session.add(ref)
    await session.flush()
    return ref


async def initialize_versioning(
    session: AsyncSession,
    resource: Resource,
    created_by: UUID,
    ref_name: str = "main",
) -> Optional[ResourceVersion]:
    if not is_versioned_type(resource.type):
        return None

    head = await get_current_head(session, resource.id, ref_name=ref_name)
    if head:
        return head

    version = await create_version(
        session,
        resource.id,
        parents=[],
        content=default_content(resource.type),
        created_by=created_by,
    )
    await update_ref(session, resource.id, ref_name, version.id, created_by)
    return version
