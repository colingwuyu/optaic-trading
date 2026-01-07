/**
 * Merge Requests client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  MergeRequestCreate,
  MergeRequestOut,
  MergeApprovalIn,
  MergeApprovalOut,
  MergeExecuteOut,
} from "./types/index.js";

export interface IMergeRequestsClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class MergeRequestsClient {
  constructor(private client: IMergeRequestsClient) {}

  /**
   * Create a merge request
   */
  async create(payload: MergeRequestCreate): Promise<MergeRequestOut> {
    return this.client.request<MergeRequestOut>("/merge-requests", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get a merge request by ID
   */
  async get(mrId: UUID): Promise<MergeRequestOut> {
    return this.client.request<MergeRequestOut>(`/merge-requests/${mrId}`);
  }

  /**
   * List merge requests
   */
  async list(params?: {
    targetResourceId?: UUID;
    status?: string;
    limit?: number;
    cursor?: string;
  }): Promise<{ items: MergeRequestOut[]; next_cursor?: string | null }> {
    const search = new URLSearchParams();
    if (params?.targetResourceId)
      search.set("target_resource_id", params.targetResourceId);
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<{
      items: MergeRequestOut[];
      next_cursor?: string | null;
    }>(`/merge-requests${query ? `?${query}` : ""}`);
  }

  /**
   * Approve or reject a merge request
   */
  async approve(
    mrId: UUID,
    payload: MergeApprovalIn
  ): Promise<MergeApprovalOut> {
    return this.client.request<MergeApprovalOut>(
      `/merge-requests/${mrId}/approve`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Execute merge (apply changes to target)
   */
  async merge(mrId: UUID): Promise<MergeExecuteOut> {
    return this.client.request<MergeExecuteOut>(`/merge-requests/${mrId}/merge`, {
      method: "POST",
    });
  }

  /**
   * Close a merge request without merging
   */
  async close(mrId: UUID): Promise<MergeRequestOut> {
    return this.client.request<MergeRequestOut>(`/merge-requests/${mrId}/close`, {
      method: "POST",
    });
  }
}
