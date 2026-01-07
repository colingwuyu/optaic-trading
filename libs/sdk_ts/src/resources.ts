/**
 * Resources client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  ResourceOut,
  ResourcePage,
  ResourceTree,
  ResourceCreate,
  ResourceUpdate,
} from "./types/index.js";

export interface IResourcesClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class ResourcesClient {
  constructor(private client: IResourcesClient) {}

  /**
   * Create a new resource
   */
  async create(payload: ResourceCreate): Promise<ResourceOut> {
    return this.client.request<ResourceOut>("/resources", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get a resource by ID
   */
  async get(resourceId: UUID): Promise<ResourceOut> {
    return this.client.request<ResourceOut>(`/resources/${resourceId}`);
  }

  /**
   * List children of a resource
   */
  async listChildren(
    resourceId: UUID,
    params?: { limit?: number; cursor?: string }
  ): Promise<ResourcePage> {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<ResourcePage>(
      `/resources/${resourceId}/children${query ? `?${query}` : ""}`
    );
  }

  /**
   * Get resource tree
   */
  async getTree(resourceId: UUID, depth = 2): Promise<ResourceTree> {
    const search = new URLSearchParams({ depth: String(depth) });
    return this.client.request<ResourceTree>(
      `/resources/${resourceId}/tree?${search}`
    );
  }

  /**
   * Update a resource
   */
  async update(
    resourceId: UUID,
    payload: ResourceUpdate
  ): Promise<ResourceOut> {
    return this.client.request<ResourceOut>(`/resources/${resourceId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Delete a resource
   */
  async delete(resourceId: UUID): Promise<ResourceOut> {
    return this.client.request<ResourceOut>(`/resources/${resourceId}`, {
      method: "DELETE",
    });
  }

  /**
   * Move a resource to a new parent
   */
  async move(resourceId: UUID, newParentId: UUID): Promise<ResourceOut> {
    return this.client.request<ResourceOut>(`/resources/${resourceId}/move`, {
      method: "POST",
      body: JSON.stringify({ new_parent_id: newParentId }),
    });
  }

  /**
   * Copy a resource to a new parent
   */
  async copy(
    resourceId: UUID,
    targetParentId: UUID,
    newName?: string
  ): Promise<ResourceOut> {
    const payload: Record<string, unknown> = {
      target_parent_id: targetParentId,
    };
    if (newName) payload.new_name = newName;
    return this.client.request<ResourceOut>(`/resources/${resourceId}/copy`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
}
