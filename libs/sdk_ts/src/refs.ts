/**
 * Refs (branches/tags) client for OptAIC TypeScript SDK
 */

import type { UUID, RefOut, BranchCreate } from "./types/index.js";

export interface IRefsClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class RefsClient {
  constructor(private client: IRefsClient) {}

  /**
   * Create a new branch
   */
  async createBranch(
    resourceId: UUID,
    payload: BranchCreate
  ): Promise<RefOut> {
    return this.client.request<RefOut>(`/refs/${resourceId}/branches`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * List branches for a resource
   */
  async listBranches(resourceId: UUID): Promise<RefOut[]> {
    return this.client.request<RefOut[]>(`/refs/${resourceId}/branches`);
  }

  /**
   * Delete a branch
   */
  async deleteBranch(resourceId: UUID, refName: string): Promise<RefOut> {
    return this.client.request<RefOut>(
      `/refs/${resourceId}/branches/${refName}`,
      {
        method: "DELETE",
      }
    );
  }

  /**
   * Create a new tag
   */
  async createTag(
    resourceId: UUID,
    tagName: string,
    versionId?: UUID
  ): Promise<RefOut> {
    const payload: Record<string, unknown> = { tag_name: tagName };
    if (versionId) payload.version_id = versionId;
    return this.client.request<RefOut>(`/refs/${resourceId}/tags`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * List tags for a resource
   */
  async listTags(resourceId: UUID): Promise<RefOut[]> {
    return this.client.request<RefOut[]>(`/refs/${resourceId}/tags`);
  }

  /**
   * Delete a tag
   */
  async deleteTag(resourceId: UUID, tagName: string): Promise<RefOut> {
    return this.client.request<RefOut>(`/refs/${resourceId}/tags/${tagName}`, {
      method: "DELETE",
    });
  }
}
