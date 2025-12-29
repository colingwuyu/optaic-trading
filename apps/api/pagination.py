from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    timestamp = created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return f"{timestamp.isoformat()}|{item_id}"

def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    if "|" not in cursor:
        raise HTTPException(status_code=400, detail="Invalid cursor format")
    timestamp_raw, item_raw = cursor.split("|", 1)
    try:
        timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor timestamp") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    try:
        item_id = UUID(item_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor id") from exc
    return timestamp, item_id
