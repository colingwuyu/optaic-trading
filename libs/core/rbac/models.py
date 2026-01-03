from enum import Enum
from typing import Optional, Any, Dict
from uuid import UUID
from pydantic import BaseModel, Field


class Permission(str, Enum):
    RESOURCE_READ = "RESOURCE_READ"
    RESOURCE_CREATE_CHILD = "RESOURCE_CREATE_CHILD"
    RESOURCE_UPDATE = "RESOURCE_UPDATE"
    RESOURCE_DELETE = "RESOURCE_DELETE"
    RBAC_GRANT = "RBAC_GRANT"
    RBAC_REVOKE = "RBAC_REVOKE"
    RBAC_VIEW = "RBAC_VIEW"
    INVITE_CREATE = "INVITE_CREATE"
    INVITE_ACCEPT = "INVITE_ACCEPT"
    INVITE_REJECT = "INVITE_REJECT"
    OWNER_TRANSFER_REQUEST = "OWNER_TRANSFER_REQUEST"
    OWNER_TRANSFER_ACCEPT = "OWNER_TRANSFER_ACCEPT"
    BRANCH_CREATE = "BRANCH_CREATE"
    MERGE_REQUEST_CREATE = "MERGE_REQUEST_CREATE"
    MERGE_APPROVE = "MERGE_APPROVE"
    MERGE_EXECUTE = "MERGE_EXECUTE"
    PROMOTE_REQUEST_CREATE = "PROMOTE_REQUEST_CREATE"
    PROMOTE_APPROVE = "PROMOTE_APPROVE"
    PROMOTE_EXECUTE = "PROMOTE_EXECUTE"
    SUBSCRIBE_RESOURCE = "SUBSCRIBE_RESOURCE"
    SUBSCRIBE_DESCENDANTS = "SUBSCRIBE_DESCENDANTS"
    VIEW_ACTIVITY_FEED = "VIEW_ACTIVITY_FEED"
    # Chat
    CHANNEL_POST = "CHANNEL_POST"
    CHANNEL_EDIT_OWN = "CHANNEL_EDIT_OWN"
    CHANNEL_DELETE_OWN = "CHANNEL_DELETE_OWN"
    CHANNEL_MODERATE = "CHANNEL_MODERATE"
    CHANNEL_VIEW_HISTORY = "CHANNEL_VIEW_HISTORY"


GLOBAL_RESOURCE_TYPE = "*"


class ActorContext(BaseModel):
    id: UUID
    tenant_id: UUID
    traits: Dict[str, Any] = Field(default_factory=dict)
    kind: Optional[str] = None


class DecisionExplanation(BaseModel):
    message: str
    binding_id: Optional[UUID] = None
    role: Optional[str] = None
    scope_resource_id: Optional[UUID] = None
    inherited: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class AuthzDecision(BaseModel):
    allowed: bool
    explanation: DecisionExplanation
    resource_id: UUID
    actor_id: UUID
    action: str
