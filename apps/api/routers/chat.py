from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agent_utils import AgentMeta, record_agent_activities
from apps.api.attachments_service import create_upload_init
from apps.api.deps import get_actor, get_agent_meta, get_db, reset_session, utcnow
from apps.api.pagination import decode_cursor, encode_cursor
from apps.api.rbac_utils import authorize_or_403, get_resource_or_404
from apps.api.schemas import (
    AttachmentUploadInitIn,
    AttachmentUploadInitOut,
    ChannelCreate,
    ChannelOut,
    MessageCreate,
    MessageOut,
    MessagePage,
    MessageUpdate,
    ReadReceiptIn,
    ReadReceiptOut,
)
from libs.core.activity import ActivityEnvelope, tx_activity
from libs.core.rbac.models import ActorContext, Permission
from libs.db.models.chat import Channel, Message, ReadReceipt
from libs.db.models.resource import Resource

router = APIRouter(prefix="/chat", tags=["Chat"])


async def get_channel_or_404(
    db: AsyncSession, tenant_id: UUID, channel_id: UUID
) -> tuple[Channel, Resource]:
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


async def get_message_or_404(
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


@router.post(
    "/channels",
    response_model=ChannelOut,
    status_code=201,
)
async def create_channel(
    payload: ChannelCreate = Body(
        ...,
        examples={
            "default": {
                "summary": "Create channel",
                "value": {
                    "parent_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1",
                    "channel_kind": "group",
                    "name": "Product Updates",
                    "topic": "Roadmap discussion",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ChannelOut:
    parent = await get_resource_or_404(db, actor.tenant_id, payload.parent_id)
    await authorize_or_403(db, actor, Permission.CHANNEL_POST, parent.id)

    channel_id = uuid4()

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Channel:
        resource = Resource(
            id=channel_id,
            tenant_id=actor.tenant_id,
            type="Channel",
            parent_id=payload.parent_id,
            owner_principal_id=actor.id,
            name=payload.name,
            status="active",
            metadata_json={"channel_kind": payload.channel_kind},
        )
        session.add(resource)
        await session.flush()
        channel = Channel(
            resource_id=channel_id,
            tenant_id=actor.tenant_id,
            channel_kind=payload.channel_kind,
            topic=payload.topic,
            settings=payload.settings,
        )
        session.add(channel)
        await session.flush()
        return channel

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=channel_id,
        resource_type="Channel",
        action="channel.created",
        payload={
            "channel_id": str(channel_id),
            "parent_id": str(payload.parent_id),
            "channel_kind": payload.channel_kind,
        },
    )
    channel, _activity = await tx_activity(db, envelope, domain_fn)
    return ChannelOut.model_validate(channel)


@router.post("/attachments/upload-init", response_model=AttachmentUploadInitOut)
async def init_attachment_upload(
    payload: AttachmentUploadInitIn = Body(
        ...,
        examples={
            "default": {
                "summary": "Initialize upload",
                "value": {
                    "channel_id": "9b7e2b44-5a2e-4b12-8b6b-9e5f6a0cc3c1",
                    "filename": "design.png",
                    "content_type": "image/png",
                    "bytes": 1048576,
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> AttachmentUploadInitOut:
    return await create_upload_init(actor, db, payload)


@router.get("/channels/{channel_id}/messages", response_model=MessagePage)
async def list_messages(
    channel_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    after: Optional[datetime] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MessagePage:
    _channel, _resource = await get_channel_or_404(db, actor.tenant_id, channel_id)
    await authorize_or_403(db, actor, Permission.CHANNEL_VIEW_HISTORY, channel_id)

    query = select(Message).where(
        Message.tenant_id == actor.tenant_id,
        Message.channel_id == channel_id,
    )
    if after is not None:
        query = query.where(Message.created_at > after)
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Message.created_at < cursor_time,
                and_(
                    Message.created_at == cursor_time,
                    Message.id < cursor_id,
                ),
            )
        )
    query = query.order_by(Message.created_at.desc(), Message.id.desc()).limit(
        limit + 1
    )

    result = await db.scalars(query)
    rows = result.all()
    items = [MessageOut.model_validate(msg) for msg in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and items:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return MessagePage(items=items, next_cursor=next_cursor)


@router.post(
    "/channels/{channel_id}/messages", response_model=MessageOut, status_code=201
)
async def send_message(
    channel_id: UUID,
    payload: MessageCreate = Body(
        ...,
        examples={"default": {"summary": "Send message", "value": {"body": "Hello"}}},
    ),
    actor: ActorContext = Depends(get_actor),
    agent_meta: AgentMeta = Depends(get_agent_meta),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    _channel, resource = await get_channel_or_404(db, actor.tenant_id, channel_id)
    await authorize_or_403(db, actor, Permission.CHANNEL_POST, channel_id)

    message_id = uuid4()
    resource_type = resource.type

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Message:
        message = Message(
            id=message_id,
            tenant_id=actor.tenant_id,
            channel_id=channel_id,
            sender_principal_id=actor.id,
            body=payload.body,
            body_json=payload.body_json,
            status="active",
        )
        session.add(message)
        await session.flush()
        if actor.kind == "agent" and agent_meta.has_agent_data():
            _channel, refreshed_resource = await get_channel_or_404(
                session, actor.tenant_id, channel_id
            )
            await record_agent_activities(
                session,
                tenant_id=actor.tenant_id,
                actor_principal_id=actor.id,
                resource=refreshed_resource,
                message_id=message_id,
                meta=agent_meta,
            )
        return message

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=channel_id,
        resource_type=resource_type,
        action="message.posted",
        payload={"message_id": str(message_id), "channel_id": str(channel_id)},
    )
    message, _activity = await tx_activity(db, envelope, domain_fn)
    return MessageOut.model_validate(message)


@router.patch("/messages/{message_id}", response_model=MessageOut)
async def edit_message(
    message_id: UUID,
    payload: MessageUpdate = Body(
        ...,
        examples={"default": {"summary": "Edit message", "value": {"body": "Updated"}}},
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    message = await get_message_or_404(db, actor.tenant_id, message_id)
    if message.sender_principal_id != actor.id:
        raise HTTPException(
            status_code=403, detail="Cannot edit another user's message"
        )
    await authorize_or_403(db, actor, Permission.CHANNEL_EDIT_OWN, message.channel_id)

    channel_id = message.channel_id

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Message:
        target = await get_message_or_404(session, actor.tenant_id, message_id)
        if target.sender_principal_id != actor.id:
            raise HTTPException(
                status_code=403, detail="Cannot edit another user's message"
            )
        target.body = payload.body
        target.body_json = payload.body_json
        target.edited_at = utcnow()
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=channel_id,
        resource_type="Channel",
        action="message.edited",
        payload={"message_id": str(message_id), "channel_id": str(channel_id)},
    )
    updated, _activity = await tx_activity(db, envelope, domain_fn)
    return MessageOut.model_validate(updated)


@router.delete("/messages/{message_id}", response_model=MessageOut)
async def delete_message(
    message_id: UUID,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    message = await get_message_or_404(db, actor.tenant_id, message_id)
    if message.sender_principal_id != actor.id:
        raise HTTPException(
            status_code=403, detail="Cannot delete another user's message"
        )
    await authorize_or_403(db, actor, Permission.CHANNEL_DELETE_OWN, message.channel_id)

    channel_id = message.channel_id

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> Message:
        target = await get_message_or_404(session, actor.tenant_id, message_id)
        if target.sender_principal_id != actor.id:
            raise HTTPException(
                status_code=403, detail="Cannot delete another user's message"
            )
        target.status = "deleted"
        target.edited_at = utcnow()
        await session.flush()
        return target

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=channel_id,
        resource_type="Channel",
        action="message.deleted",
        payload={"message_id": str(message_id), "channel_id": str(channel_id)},
    )
    deleted, _activity = await tx_activity(db, envelope, domain_fn)
    return MessageOut.model_validate(deleted)


@router.post("/channels/{channel_id}/read", response_model=ReadReceiptOut)
async def update_read_receipt(
    channel_id: UUID,
    payload: ReadReceiptIn,
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ReadReceiptOut:
    _channel, _resource = await get_channel_or_404(db, actor.tenant_id, channel_id)
    await authorize_or_403(db, actor, Permission.CHANNEL_VIEW_HISTORY, channel_id)

    message = await get_message_or_404(
        db, actor.tenant_id, payload.last_read_message_id
    )
    if message.channel_id != channel_id:
        raise HTTPException(
            status_code=400, detail="Message does not belong to channel"
        )

    await reset_session(db)

    async def domain_fn(session: AsyncSession) -> ReadReceipt:
        stmt = (
            pg_insert(ReadReceipt)
            .values(
                tenant_id=actor.tenant_id,
                channel_id=channel_id,
                principal_id=actor.id,
                last_read_message_id=payload.last_read_message_id,
                updated_at=utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "channel_id", "principal_id"],
                set_={
                    "last_read_message_id": payload.last_read_message_id,
                    "updated_at": utcnow(),
                },
            )
            .returning(ReadReceipt)
        )
        result = await session.execute(stmt)
        receipt = result.scalar_one()
        return receipt

    envelope = ActivityEnvelope(
        tenant_id=actor.tenant_id,
        actor_principal_id=actor.id,
        resource_id=channel_id,
        resource_type="Channel",
        action="receipt.read",
        payload={
            "channel_id": str(channel_id),
            "last_read_message_id": str(payload.last_read_message_id),
        },
    )
    receipt, _activity = await tx_activity(db, envelope, domain_fn)
    return ReadReceiptOut.model_validate(receipt)
