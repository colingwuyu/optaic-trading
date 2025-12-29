from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.attachments_service import create_upload_init, finalize_attachment
from apps.api.deps import get_actor, get_db
from apps.api.schemas import (
    AttachmentFinalizeIn,
    AttachmentFinalizeOut,
    AttachmentUploadInitIn,
    AttachmentUploadInitOut,
)
from libs.core.rbac.models import ActorContext

router = APIRouter(prefix="/attachments", tags=["Attachments"])


@router.post("/upload-init", response_model=AttachmentUploadInitOut, status_code=201)
async def upload_init(
    payload: AttachmentUploadInitIn = Body(
        ...,
        examples={
            "default": {
                "summary": "Initialize attachment upload",
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


@router.post("/finalize", response_model=AttachmentFinalizeOut, status_code=201)
async def finalize(
    payload: AttachmentFinalizeIn = Body(
        ...,
        examples={
            "default": {
                "summary": "Finalize attachment",
                "value": {
                    "message_id": "11111111-1111-1111-1111-111111111111",
                    "object_key": "attachments/<tenant>/<channel>/<uuid>-design.png",
                    "checksum": "md5:deadbeef",
                },
            }
        },
    ),
    actor: ActorContext = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> AttachmentFinalizeOut:
    attachment = await finalize_attachment(actor, db, payload)
    return AttachmentFinalizeOut.model_validate(attachment)
