/**
 * Activities client for OptAIC TypeScript SDK
 */

import type { UUID, ActivityPage } from "./types/index.js";

export interface IActivitiesClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class ActivitiesClient {
  constructor(private client: IActivitiesClient) {}

  /**
   * List activities with optional filtering
   */
  async list(params?: {
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
    return this.client.request<ActivityPage>(
      `/activities${query ? `?${query}` : ""}`
    );
  }

  /**
   * Get activities for a specific resource
   */
  async getByResource(
    resourceId: UUID,
    params?: { limit?: number; cursor?: string }
  ): Promise<ActivityPage> {
    return this.list({ resourceId, ...params });
  }
}
