import { Centrifuge, type Subscription } from "centrifuge";

// Re-export all types
export * from "./types/index.js";

// Export Quant Domain Clients
export * from "./datasets.js";
export * from "./signals.js";
export * from "./ops.js";
export * from "./pipelines.js";
export * from "./experiments.js";

// Export Platform Clients
export * from "./resources.js";
export * from "./auth.js";
export * from "./chat.js";
export * from "./activities.js";
export * from "./audit.js";
export * from "./notifications.js";
export * from "./subscriptions.js";
export * from "./promotions.js";
export * from "./merge-requests.js";
export * from "./refs.js";
export * from "./rbac.js";
export * from "./governance.js";
export * from "./definitions.js";
export * from "./admin.js";
export * from "./health.js";
export * from "./system.js";

// Import clients for ApiClient
import { DatasetsClient, type IApiClient } from "./datasets.js";
import { SignalsClient } from "./signals.js";
import { OpsClient } from "./ops.js";
import { PipelinesClient } from "./pipelines.js";
import { ExperimentsClient } from "./experiments.js";
import { ResourcesClient } from "./resources.js";
import { AuthClient } from "./auth.js";
import { ChatClient } from "./chat.js";
import { ActivitiesClient } from "./activities.js";
import { AuditClient } from "./audit.js";
import { NotificationsClient } from "./notifications.js";
import { SubscriptionsClient } from "./subscriptions.js";
import { PromotionsClient } from "./promotions.js";
import { MergeRequestsClient } from "./merge-requests.js";
import { RefsClient } from "./refs.js";
import { RbacClient } from "./rbac.js";
import { GovernanceClient } from "./governance.js";
import { DefinitionsClient } from "./definitions.js";
import { TenantsClient, PrincipalsClient, AdminClient } from "./admin.js";
import { HealthClient } from "./health.js";
import { SystemClient } from "./system.js";

import type {
  UUID,
  ApiClientOptions,
  ActivityEventV1,
  RealtimeBootstrapResponse,
} from "./types/index.js";

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

  // Lazy-loaded client instances
  private _datasets?: DatasetsClient;
  private _signals?: SignalsClient;
  private _ops?: OpsClient;
  private _pipelines?: PipelinesClient;
  private _experiments?: ExperimentsClient;
  private _resources?: ResourcesClient;
  private _auth?: AuthClient;
  private _chat?: ChatClient;
  private _activities?: ActivitiesClient;
  private _audit?: AuditClient;
  private _notifications?: NotificationsClient;
  private _subscriptions?: SubscriptionsClient;
  private _promotions?: PromotionsClient;
  private _mergeRequests?: MergeRequestsClient;
  private _refs?: RefsClient;
  private _rbac?: RbacClient;
  private _governance?: GovernanceClient;
  private _definitions?: DefinitionsClient;
  private _tenants?: TenantsClient;
  private _principals?: PrincipalsClient;
  private _admin?: AdminClient;
  private _health?: HealthClient;
  private _system?: SystemClient;

  // Quant Domain Clients (lazy getters)
  get datasets(): DatasetsClient {
    return (this._datasets ??= new DatasetsClient(this));
  }
  get signals(): SignalsClient {
    return (this._signals ??= new SignalsClient(this));
  }
  get ops(): OpsClient {
    return (this._ops ??= new OpsClient(this));
  }
  get pipelines(): PipelinesClient {
    return (this._pipelines ??= new PipelinesClient(this));
  }
  get experiments(): ExperimentsClient {
    return (this._experiments ??= new ExperimentsClient(this));
  }

  // Platform Clients (lazy getters)
  get resources(): ResourcesClient {
    return (this._resources ??= new ResourcesClient(this));
  }
  get auth(): AuthClient {
    return (this._auth ??= new AuthClient(this));
  }
  get chat(): ChatClient {
    return (this._chat ??= new ChatClient(this));
  }
  get activities(): ActivitiesClient {
    return (this._activities ??= new ActivitiesClient(this));
  }
  get audit(): AuditClient {
    return (this._audit ??= new AuditClient(this));
  }
  get notifications(): NotificationsClient {
    return (this._notifications ??= new NotificationsClient(this));
  }
  get subscriptions(): SubscriptionsClient {
    return (this._subscriptions ??= new SubscriptionsClient(this));
  }
  get promotions(): PromotionsClient {
    return (this._promotions ??= new PromotionsClient(this));
  }
  get mergeRequests(): MergeRequestsClient {
    return (this._mergeRequests ??= new MergeRequestsClient(this));
  }
  get refs(): RefsClient {
    return (this._refs ??= new RefsClient(this));
  }
  get rbac(): RbacClient {
    return (this._rbac ??= new RbacClient(this));
  }
  get governance(): GovernanceClient {
    return (this._governance ??= new GovernanceClient(this));
  }
  get definitions(): DefinitionsClient {
    return (this._definitions ??= new DefinitionsClient(this));
  }
  get tenants(): TenantsClient {
    return (this._tenants ??= new TenantsClient(this));
  }
  get principals(): PrincipalsClient {
    return (this._principals ??= new PrincipalsClient(this));
  }
  get admin(): AdminClient {
    return (this._admin ??= new AdminClient(this));
  }
  get health(): HealthClient {
    return (this._health ??= new HealthClient(this));
  }
  get system(): SystemClient {
    return (this._system ??= new SystemClient(this));
  }

  constructor(baseUrl: string, options: ApiClientOptions = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    const fallbackFetcher =
      typeof fetch === "function" ? fetch.bind(globalThis) : undefined;
    if (!options.fetcher && !fallbackFetcher) {
      throw new Error("fetch is not available in this environment");
    }
    this.fetcher = options.fetcher ?? (fallbackFetcher as typeof fetch);

    // Build headers based on auth method
    this.headers = {
      "Content-Type": "application/json",
      ...options.headers,
    };

    // API Key authentication (highest priority)
    if (options.apiKey) {
      this.headers["X-API-Key"] = options.apiKey;
    }
    // OAuth token authentication
    else if (options.oauthToken) {
      this.headers["Authorization"] = `Bearer ${options.oauthToken}`;
    }

    // Dev mode headers (can be combined with API key)
    if (options.tenantId) {
      this.headers["X-Tenant-Id"] = options.tenantId;
    }
    if (options.principalId) {
      this.headers["X-Principal-Id"] = options.principalId;
    }
  }

  /**
   * Set tenant ID for dev mode
   */
  setTenantId(tenantId: UUID): void {
    this.headers["X-Tenant-Id"] = tenantId;
  }

  /**
   * Set principal ID for dev mode
   */
  setPrincipalId(principalId: UUID): void {
    this.headers["X-Principal-Id"] = principalId;
  }

  /**
   * Set API key for authentication
   */
  setApiKey(apiKey: string): void {
    this.headers["X-API-Key"] = apiKey;
    // Remove OAuth token if API key is set
    delete this.headers["Authorization"];
  }

  /**
   * Set OAuth token for authentication
   */
  setOAuthToken(token: string): void {
    this.headers["Authorization"] = `Bearer ${token}`;
    // Remove API key if OAuth token is set
    delete this.headers["X-API-Key"];
  }

  public async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    // Merge headers, but allow init to override Content-Type (for FormData)
    const requestHeaders = { ...this.headers };
    if (init.headers) {
      Object.assign(requestHeaders, init.headers);
    }
    // If body is FormData, remove Content-Type so browser sets multipart boundary
    if (init.body instanceof FormData) {
      delete requestHeaders["Content-Type"];
    }

    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      ...init,
      headers: requestHeaders,
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

  /**
   * Get realtime bootstrap data for WebSocket connection
   */
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
    handler: (ctx: unknown) => void
  ): void {
    this.listeners[event].push(handler);
    if (this.client) {
      this.client.on(event, handler);
    }
  }

  connect(connectionToken: string): void {
    if (!this.client) {
      this.client = new Centrifuge(this.url, { token: connectionToken });
      (
        Object.keys(this.listeners) as Array<
          "connecting" | "connected" | "disconnected"
        >
      ).forEach((event) => {
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
    handler: (data: ActivityEventV1) => void
  ): Subscription {
    if (!this.client) {
      throw new Error("RealtimeClient not connected");
    }
    const subscription = this.client.newSubscription(channel, { token });
    subscription.on("publication", (ctx) =>
      handler(ctx.data as ActivityEventV1)
    );
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
