/**
 * Definitions client for OptAIC TypeScript SDK
 */

import type { UUID, DefinitionOut, DefinitionCreate } from "./types/index.js";

export interface IDefinitionsClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class DefinitionsClient {
  constructor(private client: IDefinitionsClient) {}

  /**
   * Register a new definition
   */
  async register(payload: DefinitionCreate): Promise<DefinitionOut> {
    return this.client.request<DefinitionOut>("/definitions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get a definition by ID
   */
  async get(definitionId: UUID): Promise<DefinitionOut> {
    return this.client.request<DefinitionOut>(`/definitions/${definitionId}`);
  }

  /**
   * Get a definition by name and version
   */
  async getByNameVersion(
    name: string,
    version: string
  ): Promise<DefinitionOut> {
    const search = new URLSearchParams({ name, version });
    return this.client.request<DefinitionOut>(`/definitions/lookup?${search}`);
  }

  /**
   * List definitions
   */
  async list(params?: {
    kind?: string;
    name?: string;
    status?: string;
    limit?: number;
    cursor?: string;
  }): Promise<{ items: DefinitionOut[]; next_cursor?: string | null }> {
    const search = new URLSearchParams();
    if (params?.kind) search.set("kind", params.kind);
    if (params?.name) search.set("name", params.name);
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<{
      items: DefinitionOut[];
      next_cursor?: string | null;
    }>(`/definitions${query ? `?${query}` : ""}`);
  }

  /**
   * Deprecate a definition
   */
  async deprecate(definitionId: UUID): Promise<DefinitionOut> {
    return this.client.request<DefinitionOut>(
      `/definitions/${definitionId}/deprecate`,
      {
        method: "POST",
      }
    );
  }

  /**
   * Upload a plugin/module file for a definition
   */
  async uploadPlugin(
    definitionId: UUID,
    file: File | Blob,
    filename: string
  ): Promise<{ object_key: string }> {
    const formData = new FormData();
    formData.append("file", file, filename);
    return this.client.request<{ object_key: string }>(
      `/definitions/${definitionId}/upload`,
      {
        method: "POST",
        body: formData,
        // Remove Content-Type header so browser sets multipart/form-data with boundary
        headers: {},
      }
    );
  }
}
