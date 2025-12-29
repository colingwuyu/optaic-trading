from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class ActivityEnvelope(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utcnow)
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    payload: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
