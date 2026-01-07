/**
 * Audit client for OptAIC TypeScript SDK
 */

import type { UUID, AuditLogPage, AuditCountOut } from "./types/index.js";

export interface IAuditClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class AuditClient {
  constructor(private client: IAuditClient) {}

  /**
   * Search audit logs with filtering
   */
  async search(params?: {
    actorPrincipalId?: UUID;
    resourceId?: UUID;
    action?: string;
    after?: string;
    before?: string;
    limit?: number;
    cursor?: string;
  }): Promise<AuditLogPage> {
    const search = new URLSearchParams();
    if (params?.actorPrincipalId)
      search.set("actor_principal_id", params.actorPrincipalId);
    if (params?.resourceId) search.set("resource_id", params.resourceId);
    if (params?.action) search.set("action", params.action);
    if (params?.after) search.set("after", params.after);
    if (params?.before) search.set("before", params.before);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<AuditLogPage>(
      `/audit-logs${query ? `?${query}` : ""}`
    );
  }

  /**
   * Count audit log entries matching filters
   */
  async count(params?: {
    actorPrincipalId?: UUID;
    resourceId?: UUID;
    action?: string;
    after?: string;
    before?: string;
  }): Promise<AuditCountOut> {
    const search = new URLSearchParams();
    if (params?.actorPrincipalId)
      search.set("actor_principal_id", params.actorPrincipalId);
    if (params?.resourceId) search.set("resource_id", params.resourceId);
    if (params?.action) search.set("action", params.action);
    if (params?.after) search.set("after", params.after);
    if (params?.before) search.set("before", params.before);
    const query = search.toString();
    return this.client.request<AuditCountOut>(
      `/audit-logs/count${query ? `?${query}` : ""}`
    );
  }
}
