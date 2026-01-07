/**
 * Shared types for OptAIC TypeScript SDK
 */

export type UUID = string;

export type AuthzDecision = "allow" | "deny";

// =========================================================================
// Activity Types
// =========================================================================

export interface ActivityActor {
  principal_id: UUID;
  kind: string;
  display_name?: string | null;
}

export interface ActivityResource {
  resource_id: UUID;
  resource_type: string;
  parent_id?: UUID | null;
}

export interface ActivityUiHints {
  category?: string | null;
  severity?: string | null;
  icon?: string | null;
  title?: string | null;
  summary?: string | null;
}

export interface ActivityTargets {
  user_inbox?: UUID[] | null;
  chat_channels?: UUID[] | null;
  resource_channels?: UUID[] | null;
}

export interface ActivityEventV1 {
  version: "1";
  event_id: UUID;
  tenant_id: UUID;
  created_at: string;
  correlation_id: UUID;
  actor: ActivityActor;
  resource: ActivityResource;
  action: string;
  target_principal_id?: UUID | null;
  visibility: string;
  payload: Record<string, unknown>;
  authz_decision?: AuthzDecision | null;
  ui_hints?: ActivityUiHints | null;
  targets?: ActivityTargets | null;
}

export interface ActivityPage {
  items: ActivityEventV1[];
  next_cursor?: string | null;
}

// =========================================================================
// Resource Types
// =========================================================================

export interface ResourceOut {
  id: UUID;
  tenant_id: UUID;
  type: string;
  parent_id?: UUID | null;
  owner_principal_id: UUID;
  name: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ResourcePage {
  items: ResourceOut[];
  next_cursor?: string | null;
}

export interface ResourceTree {
  resource: ResourceOut;
  children: ResourceTree[];
}

export interface ResourceCreate {
  type: string;
  parent_id: UUID;
  name: string;
  metadata?: Record<string, unknown>;
}

export interface ResourceUpdate {
  name?: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

// =========================================================================
// Tenant & Principal Types
// =========================================================================

export interface TenantOut {
  id: UUID;
  name: string;
  created_at: string;
  root_resource_id?: UUID | null;
}

export interface PrincipalOut {
  id: UUID;
  tenant_id: UUID;
  kind: string;
  status: string;
  display_name: string;
  email?: string | null;
  created_at: string;
}

export interface PrincipalCreate {
  id?: UUID;
  kind?: string;
  status?: string;
  display_name: string;
  email?: string | null;
}

// =========================================================================
// Chat Types
// =========================================================================

export interface ChannelOut {
  id: UUID;
  resource_id: UUID;
  tenant_id: UUID;
  name: string;
  channel_kind: string;
  topic?: string | null;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface ChannelCreate {
  parent_id: UUID;
  channel_kind: string;
  name: string;
  topic?: string | null;
  settings?: Record<string, unknown>;
}

export interface MessageOut {
  id: UUID;
  tenant_id: UUID;
  channel_id: UUID;
  sender_principal_id: UUID;
  body?: string | null;
  body_json?: Record<string, unknown> | null;
  status: string;
  edited_at?: string | null;
  created_at: string;
}

export interface MessagePage {
  items: MessageOut[];
  next_cursor?: string | null;
}

export interface MessageCreate {
  body: string;
  body_json?: Record<string, unknown> | null;
}

export interface AttachmentUploadInitOut {
  presigned_put_url: string;
  upload_url?: string | null;
  object_key: string;
  headers: Record<string, string>;
  expires_in: number;
}

export interface AttachmentFinalizeOut {
  id: UUID;
  tenant_id: UUID;
  message_id: UUID;
  object_key: string;
  filename: string;
  content_type: string;
  bytes: number;
  checksum: string;
  created_at: string;
}

// =========================================================================
// Merge Request Types
// =========================================================================

export interface MergeRequestCreate {
  target_resource_id: UUID;
  source_ref: string;
  target_ref?: string;
  title?: string;
  description?: string;
  required_approvals?: number;
}

export interface MergeRequestOut {
  id: UUID;
  tenant_id: UUID;
  mr_resource_id: UUID;
  target_resource_id: UUID;
  source_ref: string;
  target_ref: string;
  status: string;
  required_approvals: number;
  title?: string | null;
  description?: string | null;
  created_by: UUID;
  created_at: string;
  updated_at: string;
}

export interface MergeApprovalIn {
  decision: "approve" | "reject";
  comment?: string;
}

export interface MergeApprovalOut {
  mr_id: UUID;
  decision: "approve" | "reject";
  approvals: number;
  rejects: number;
  required_approvals: number;
  status: string;
}

export interface MergeExecuteOut {
  mr_id: UUID;
  target_resource_id: UUID;
  target_ref: string;
  new_version_id: UUID;
  status: string;
}

// =========================================================================
// Promotion Types
// =========================================================================

export interface PromotionCreate {
  moving_resource_id: UUID;
  to_scope_id: UUID;
  placement: Record<string, unknown>;
  mode: "move" | "copy";
  rbac_template_ref?: string | null;
}

export interface PromotionRequestOut {
  id: UUID;
  tenant_id: UUID;
  pr_resource_id: UUID;
  moving_resource_id: UUID;
  from_scope_id?: UUID | null;
  to_scope_id: UUID;
  placement: Record<string, unknown>;
  rbac_template_ref?: string | null;
  mode: string;
  status: string;
  required_approvals: number;
  created_by: UUID;
  created_at: string;
  updated_at: string;
}

export interface PromotionApprovalIn {
  decision: "approve" | "reject";
  comment?: string;
}

export interface PromotionApprovalOut {
  pr_id: UUID;
  decision: "approve" | "reject";
  approvals: number;
  rejects: number;
  required_approvals: number;
  status: string;
}

export interface PromotionExecuteOut {
  pr_id: UUID;
  status: string;
  mode: string;
  new_root_id?: UUID | null;
  moved_count: number;
  copied_count: number;
}

// =========================================================================
// Realtime Types
// =========================================================================

export interface RealtimeBootstrapChannel {
  id: UUID;
  name: string;
  channel: string;
}

export interface RealtimeBootstrapResource {
  resource_id: UUID;
  channel: string;
}

export interface RealtimeBootstrapResponse {
  tenant_id: UUID;
  principal_id: UUID;
  inbox_channel: string;
  chat_channels: RealtimeBootstrapChannel[];
  resource_subscriptions: RealtimeBootstrapResource[];
  connection_token: string;
  subscription_tokens: Record<string, string>;
}

// =========================================================================
// Auth Types
// =========================================================================

export interface ApiKeyCreate {
  name: string;
  description?: string | null;
  scopes?: string[] | null;
  expires_in_days?: number | null;
}

export interface ApiKeyOut {
  id: UUID;
  tenant_id: UUID;
  principal_id: UUID;
  name: string;
  description?: string | null;
  scopes: string[];
  key_prefix: string;
  created_at: string;
  expires_at?: string | null;
  revoked_at?: string | null;
}

export interface ApiKeyCreateOut extends ApiKeyOut {
  full_key: string;
}

export interface CurrentUserOut {
  principal_id: UUID;
  tenant_id: UUID;
  auth_method: string;
  display_name?: string | null;
  email?: string | null;
}

// =========================================================================
// Audit Types
// =========================================================================

export interface AuditLogEntry {
  id: UUID;
  tenant_id: UUID;
  event_id: UUID;
  actor_principal_id: UUID;
  resource_id?: UUID | null;
  action: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  next_cursor?: string | null;
}

export interface AuditCountOut {
  count: number;
}

// =========================================================================
// Notification Types
// =========================================================================

export interface NotificationOut {
  id: UUID;
  tenant_id: UUID;
  principal_id: UUID;
  activity_id: UUID;
  read: boolean;
  created_at: string;
  activity?: ActivityEventV1 | null;
}

export interface NotificationPage {
  items: NotificationOut[];
  next_cursor?: string | null;
  unread_count: number;
}

export interface NotificationPreference {
  id: UUID;
  tenant_id: UUID;
  principal_id: UUID;
  filter_mode: "all" | "mutations" | "custom";
  custom_actions: string[];
  muted: boolean;
  updated_at: string;
}

// =========================================================================
// Subscription Types
// =========================================================================

export interface SubscriptionOut {
  id: UUID;
  tenant_id: UUID;
  principal_id: UUID;
  resource_id: UUID;
  scope: "resource" | "descendants";
  created_at: string;
  revoked_at?: string | null;
}

export interface SubscriptionCreate {
  resource_id: UUID;
  scope: "resource" | "descendants";
}

// =========================================================================
// RBAC Types
// =========================================================================

export interface RoleBindingOut {
  id: UUID;
  tenant_id: UUID;
  principal_id: UUID;
  role_name: string;
  scope_resource_id: UUID;
  granted_by: UUID;
  granted_at: string;
  revoked_at?: string | null;
}

export interface EffectivePermissions {
  principal_id: UUID;
  resource_id: UUID;
  roles: string[];
  permissions: string[];
}

// =========================================================================
// Ref/Branch Types
// =========================================================================

export interface RefOut {
  resource_id: UUID;
  ref_name: string;
  ref_type: "branch" | "tag";
  version_id: UUID;
  created_at: string;
}

export interface BranchCreate {
  ref_name: string;
  from_ref?: string;
}

// =========================================================================
// Governance Types
// =========================================================================

export interface GovernanceOperationOut {
  operation: string;
  resource_id: UUID;
  target_resource_id?: UUID;
  promotion_request_id?: UUID;
}

export interface TransferRequestOut {
  id: UUID;
  tenant_id: UUID;
  resource_id: UUID;
  sender_id: UUID;
  recipient_id: UUID;
  status: "pending" | "accepted" | "rejected" | "cancelled";
  message?: string | null;
  response_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface LineageEntry {
  resource_id: UUID;
  resource_name: string;
  resource_type: string;
  edge_type: string;
  depth: number;
}

export interface LineageOut {
  resource_id: UUID;
  direction: "upstream" | "downstream";
  entries: LineageEntry[];
}

// =========================================================================
// Health Types
// =========================================================================

export interface HealthOut {
  status: string;
  version?: string;
  timestamp?: string;
}

// =========================================================================
// Definition Types
// =========================================================================

export interface DefinitionOut {
  id: UUID;
  tenant_id: UUID;
  name: string;
  kind: string;
  version: string;
  interface_spec: Record<string, unknown>;
  status: string;
  created_at: string;
  deprecated_at?: string | null;
}

export interface DefinitionCreate {
  name: string;
  kind: string;
  version: string;
  interface_spec: Record<string, unknown>;
}

// =========================================================================
// Client Options
// =========================================================================

export interface ApiClientOptions {
  tenantId?: UUID;
  principalId?: UUID;
  apiKey?: string;
  oauthToken?: string;
  fetcher?: typeof fetch;
  headers?: Record<string, string>;
}
