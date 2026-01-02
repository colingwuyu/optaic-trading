import { Centrifuge, type Subscription } from "centrifuge";
import { DatasetsClient, type IApiClient } from "./datasets.js";
import { SignalsClient } from "./signals.js";
import { OpsClient } from "./ops.js";
import { PipelinesClient } from "./pipelines.js";
import { ExperimentsClient } from "./experiments.js";

export * from "./datasets.js";
export * from "./signals.js";
export * from "./ops.js";
export * from "./pipelines.js";
export * from "./experiments.js";

export type UUID = string;

export type AuthzDecision = "allow" | "deny";

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

export interface ChannelOut {
  resource_id: UUID;
  tenant_id: UUID;
  channel_kind: string;
  topic?: string | null;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface ActivityPage {
  items: ActivityEventV1[];
  next_cursor?: string | null;
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

export interface ApiClientOptions {
  tenantId: UUID;
  principalId: UUID;
  fetcher?: typeof fetch;
  headers?: Record<string, string>;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

export class ApiClient implements IApiClient {
  private baseUrl: string;
  private headers: Record<string, string>;
  private fetcher: typeof fetch;

  public datasets: DatasetsClient;
  public signals: SignalsClient;
  public ops: OpsClient;
  public pipelines: PipelinesClient;
  public experiments: ExperimentsClient;

  constructor(baseUrl: string, options: ApiClientOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    const fallbackFetcher =
      typeof fetch === "function" ? fetch.bind(globalThis) : undefined;
    if (!options.fetcher && !fallbackFetcher) {
      throw new Error("fetch is not available in this environment");
    }
    this.fetcher = options.fetcher ?? (fallbackFetcher as typeof fetch);
    this.headers = {
      "Content-Type": "application/json",
      "X-Tenant-Id": options.tenantId,
      "X-Principal-Id": options.principalId,
      ...options.headers,
    };

    // Initialize Quant Domain Clients
    this.datasets = new DatasetsClient(this);
    this.signals = new SignalsClient(this);
    this.ops = new OpsClient(this);
    this.pipelines = new PipelinesClient(this);
    this.experiments = new ExperimentsClient(this);
  }

  public async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...this.headers,
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new ApiError(response.status, detail || response.statusText);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  }

  listResources(
    parentId: UUID,
    params?: { limit?: number; cursor?: string },
  ): Promise<ResourcePage> {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.request<ResourcePage>(
      `/resources/${parentId}/children${query ? `?${query}` : ""}`,
    );
  }

  getTree(resourceId: UUID, depth = 2): Promise<ResourceTree> {
    const search = new URLSearchParams({ depth: String(depth) });
    return this.request<ResourceTree>(`/resources/${resourceId}/tree?${search}`);
  }

  createResource(payload: ResourceCreate): Promise<ResourceOut> {
    return this.request<ResourceOut>("/resources", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  moveResource(resourceId: UUID, newParentId: UUID): Promise<ResourceOut> {
    return this.request<ResourceOut>(`/resources/${resourceId}/move`, {
      method: "POST",
      body: JSON.stringify({ new_parent_id: newParentId }),
    });
  }

  createTenant(payload: { name: string }): Promise<TenantOut> {
    return this.request<TenantOut>("/tenants", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  createPrincipal(payload: {
    id?: UUID;
    kind?: string;
    status?: string;
    display_name: string;
    email?: string | null;
  }): Promise<PrincipalOut> {
    return this.request<PrincipalOut>("/principals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  listActivities(params?: {
    resourceId?: UUID;
    limit?: number;
    cursor?: string;
    after?: string;
  }): Promise<ActivityPage> {
    const search = new URLSearchParams();
    if (params?.resourceId) search.set("resource_id", params.resourceId);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    if (params?.after) search.set("after", params.after);
    const query = search.toString();
    return this.request<ActivityPage>(
      `/activities${query ? `?${query}` : ""}`,
    );
  }

  createInvite(payload: Record<string, unknown>): Promise<unknown> {
    return this.request<unknown>("/invites", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  acceptInvite(inviteId: UUID, payload?: Record<string, unknown>): Promise<unknown> {
    return this.request<unknown>(`/invites/${inviteId}/accept`, {
      method: "POST",
      body: payload ? JSON.stringify(payload) : undefined,
    });
  }

  async listChannels(
    parentId: UUID,
    params?: { limit?: number; cursor?: string },
  ): Promise<ResourcePage> {
    const page = await this.listResources(parentId, params);
    return {
      items: page.items.filter((item) => item.type === "Channel"),
      next_cursor: page.next_cursor,
    };
  }

  createChannel(payload: {
    parent_id: UUID;
    channel_kind: string;
    name: string;
    topic?: string | null;
    settings?: Record<string, unknown>;
  }): Promise<ChannelOut> {
    return this.request<ChannelOut>("/chat/channels", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  getMessages(
    channelId: UUID,
    params?: { limit?: number; cursor?: string; after?: string },
  ): Promise<MessagePage> {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    if (params?.after) search.set("after", params.after);
    const query = search.toString();
    return this.request<MessagePage>(
      `/chat/channels/${channelId}/messages${query ? `?${query}` : ""}`,
    );
  }

  sendMessage(
    channelId: UUID,
    payload: { body: string; body_json?: Record<string, unknown> | null },
  ): Promise<MessageOut> {
    return this.request<MessageOut>(`/chat/channels/${channelId}/messages`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  editMessage(
    messageId: UUID,
    payload: { body: string; body_json?: Record<string, unknown> | null },
  ): Promise<MessageOut> {
    return this.request<MessageOut>(`/chat/messages/${messageId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  deleteMessage(messageId: UUID): Promise<MessageOut> {
    return this.request<MessageOut>(`/chat/messages/${messageId}`, {
      method: "DELETE",
    });
  }

  uploadAttachmentInit(payload: {
    channel_id: UUID;
    filename: string;
    content_type: string;
    bytes: number;
    checksum?: string | null;
  }): Promise<AttachmentUploadInitOut> {
    return this.request<AttachmentUploadInitOut>("/attachments/upload-init", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  finalizeAttachment(payload: {
    message_id: UUID;
    object_key: string;
    checksum?: string | null;
  }): Promise<AttachmentFinalizeOut> {
    return this.request<AttachmentFinalizeOut>("/attachments/finalize", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  createMergeRequest(payload: MergeRequestCreate): Promise<MergeRequestOut> {
    return this.request<MergeRequestOut>("/merge-requests", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  getMergeRequest(mrId: UUID): Promise<MergeRequestOut> {
    return this.request<MergeRequestOut>(`/merge-requests/${mrId}`);
  }

  approveMergeRequest(
    mrId: UUID,
    payload: MergeApprovalIn,
  ): Promise<MergeApprovalOut> {
    return this.request<MergeApprovalOut>(`/merge-requests/${mrId}/approve`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  merge(mrId: UUID): Promise<MergeExecuteOut> {
    return this.request<MergeExecuteOut>(`/merge-requests/${mrId}/merge`, {
      method: "POST",
    });
  }

  createPromotion(payload: PromotionCreate): Promise<PromotionRequestOut> {
    return this.request<PromotionRequestOut>("/promotions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  getPromotion(prId: UUID): Promise<PromotionRequestOut> {
    return this.request<PromotionRequestOut>(`/promotions/${prId}`);
  }

  approvePromotion(
    prId: UUID,
    payload: PromotionApprovalIn,
  ): Promise<PromotionApprovalOut> {
    return this.request<PromotionApprovalOut>(`/promotions/${prId}/approve`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  executePromotion(prId: UUID): Promise<PromotionExecuteOut> {
    return this.request<PromotionExecuteOut>(`/promotions/${prId}/execute`, {
      method: "POST",
    });
  }

  realtimeBootstrap(): Promise<RealtimeBootstrapResponse> {
    return this.request<RealtimeBootstrapResponse>("/realtime/bootstrap");
  }
}

export class RealtimeClient {
  private url: string;
  private client: Centrifuge | null = null;
  private listeners: Record<
    "connecting" | "connected" | "disconnected",
    Array<(ctx: unknown) => void>
  > = {
    connecting: [],
    connected: [],
    disconnected: [],
  };

  constructor(url: string) {
    this.url = url;
  }

  on(
    event: "connecting" | "connected" | "disconnected",
    handler: (ctx: unknown) => void,
  ): void {
    this.listeners[event].push(handler);
    if (this.client) {
      this.client.on(event, handler);
    }
  }

  connect(connectionToken: string): void {
    if (!this.client) {
      this.client = new Centrifuge(this.url, { token: connectionToken });
      (Object.keys(this.listeners) as Array<
        "connecting" | "connected" | "disconnected"
      >).forEach((event) => {
        this.listeners[event].forEach((handler) => {
          this.client?.on(event, handler);
        });
      });
    } else {
      this.client.setToken(connectionToken);
    }
    this.client.connect();
  }

  subscribe(
    channel: string,
    token: string,
    handler: (data: ActivityEventV1) => void,
  ): Subscription {
    if (!this.client) {
      throw new Error("RealtimeClient not connected");
    }
    const subscription = this.client.newSubscription(channel, { token });
    subscription.on("publication", (ctx) => handler(ctx.data as ActivityEventV1));
    subscription.subscribe();
    return subscription;
  }

  disconnect(): void {
    if (this.client) {
      this.client.disconnect();
      this.client = null;
    }
  }
}
