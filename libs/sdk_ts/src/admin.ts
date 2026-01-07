/**
 * Admin client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  TenantOut,
  PrincipalOut,
  PrincipalCreate,
} from "./types/index.js";

export interface IAdminClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class TenantsClient {
  constructor(private client: IAdminClient) {}

  /**
   * Create a new tenant
   */
  async create(name: string): Promise<TenantOut> {
    return this.client.request<TenantOut>("/tenants", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  }

  /**
   * Get a tenant by ID
   */
  async get(tenantId: UUID): Promise<TenantOut> {
    return this.client.request<TenantOut>(`/tenants/${tenantId}`);
  }

  /**
   * List all tenants
   */
  async list(): Promise<TenantOut[]> {
    return this.client.request<TenantOut[]>("/tenants");
  }
}

export class PrincipalsClient {
  constructor(private client: IAdminClient) {}

  /**
   * Create a new principal
   */
  async create(payload: PrincipalCreate): Promise<PrincipalOut> {
    return this.client.request<PrincipalOut>("/principals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get a principal by ID
   */
  async get(principalId: UUID): Promise<PrincipalOut> {
    return this.client.request<PrincipalOut>(`/principals/${principalId}`);
  }

  /**
   * List principals
   */
  async list(): Promise<PrincipalOut[]> {
    return this.client.request<PrincipalOut[]>("/principals");
  }
}

export class AdminClient {
  public tenants: TenantsClient;
  public principals: PrincipalsClient;

  constructor(client: IAdminClient) {
    this.tenants = new TenantsClient(client);
    this.principals = new PrincipalsClient(client);
  }
}
