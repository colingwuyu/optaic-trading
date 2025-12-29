from __future__ import annotations

import os
import re
from typing import Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import reset_session
from apps.api.schemas import AttachmentFinalizeIn, AttachmentUploadInitIn, AttachmentUploadInitOut
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.core.storage import create_presigned_put, head_object
from libs.db.models.chat import Channel, Message, MessageAttachment
from libs.db.models.resource import Resource
from apps.api.rbac_utils import authorize_or_403


def _sanitize_filename(filename: str) -> str:
    basename = os.path.basename(filename)
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    sanitized = sanitized.strip("._")
    return sanitized or "file"


async def _get_channel(
    db: AsyncSession, tenant_id: UUID, channel_id: UUID
) -> Tuple[Channel, Resource]:
    result = await db.execute(
        select(Channel, Resource)
        .join(Resource, Resource.id == Channel.resource_id)
        .where(
            Channel.resource_id == channel_id,
            Channel.tenant_id == tenant_id,
            Resource.tenant_id == tenant_id,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    return row[0], row[1]


async def _get_message(
    db: AsyncSession, tenant_id: UUID, message_id: UUID
) -> Message:
    result = await db.scalars(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == tenant_id,
        )
    )
    message = result.first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


async def create_upload_init(
    actor: ActorContext,
    db: AsyncSession,
    payload: AttachmentUploadInitIn,
) -> AttachmentUploadInitOut:
    _channel, _resource = await _get_channel(db, actor.tenant_id, payload.channel_id)
    await authorize_or_403(db, actor, Permission.CHANNEL_POST, payload.channel_id)

    safe_name = _sanitize_filename(payload.filename)
    object_key = (
        f"attachments/{actor.tenant_id}/{payload.channel_id}/{uuid4()}-{safe_name}"
    )
    metadata = {"filename": safe_name, "bytes": str(payload.bytes)}
    presigned_url, headers = await create_presigned_put(
        object_key=object_key,
        content_type=payload.content_type,
        metadata=metadata,
    )
    return AttachmentUploadInitOut(
        object_key=object_key,
        presigned_put_url=presigned_url,
        upload_url=presigned_url,
        headers=headers,
        expires_in=900,
    )


async def finalize_attachment(
    actor: ActorContext,
    db: AsyncSession,
    payload: AttachmentFinalizeIn,
) -> MessageAttachment:
    message = await _get_message(db, actor.tenant_id, payload.message_id)
    if message.sender_principal_id != actor.id:
        raise HTTPException(
            status_code=403,
            detail="Cannot attach to another user's message",
        )

    try:
        head = await head_object(payload.object_key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Attachment object not found") from exc

    etag = str(head.get("etag") or "")
    checksum = payload.checksum or ""
    if checksum:
        normalized = checksum.replace("md5:", "").strip('"')
        if etag and etag != normalized:
            raise HTTPException(status_code=400, detail="Attachment checksum mismatch")

    metadata = head.get("metadata") or {}
    filename = metadata.get("filename") or _sanitize_filename(
        payload.object_key.split("/")[-1]
    )
    content_type = head.get("content_type") or "application/octet-stream"
    bytes_len = int(head.get("content_length") or 0)
    attachment_id = uuid4()

    channel_id = message.channel_id

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> MessageAttachment:
        target = await _get_message(session, actor.tenant_id, payload.message_id)
        if target.sender_principal_id != actor.id:
            raise HTTPException(
                status_code=403,
                detail="Cannot attach to another user's message",
            )
        attachment = MessageAttachment(
            id=attachment_id,
            tenant_id=actor.tenant_id,
            message_id=payload.message_id,
            object_key=payload.object_key,
            filename=filename,
            content_type=content_type,
            bytes=bytes_len,
            checksum=checksum or etag or "",
        )
        session.add(attachment)
        await session.flush()
        return attachment

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=channel_id,
        resource_type="Channel",
        action="attachment.added",
        payload={
            "message_id": str(payload.message_id),
            "attachment_id": str(attachment_id),
            "object_key": payload.object_key,
            "filename": filename,
        },
    )
    attachment, _activity = await tx_activity(db, envelope, domain_fn)
    return attachment
