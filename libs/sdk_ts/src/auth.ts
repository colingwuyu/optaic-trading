/**
 * Auth client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  ApiKeyCreate,
  ApiKeyOut,
  ApiKeyCreateOut,
  CurrentUserOut,
} from "./types/index.js";

export interface IAuthClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class AuthClient {
  constructor(private client: IAuthClient) {}

  /**
   * Create a new API key
   */
  async createApiKey(payload: ApiKeyCreate): Promise<ApiKeyCreateOut> {
    return this.client.request<ApiKeyCreateOut>("/auth/keys", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * List API keys for the current principal
   */
  async listApiKeys(includeRevoked = false): Promise<{ items: ApiKeyOut[] }> {
    const params = new URLSearchParams({
      include_revoked: String(includeRevoked),
    });
    return this.client.request<{ items: ApiKeyOut[] }>(
      `/auth/keys?${params}`
    );
  }

  /**
   * Get an API key by ID
   */
  async getApiKey(keyId: UUID): Promise<ApiKeyOut> {
    return this.client.request<ApiKeyOut>(`/auth/keys/${keyId}`);
  }

  /**
   * Revoke an API key
   */
  async revokeApiKey(keyId: UUID): Promise<ApiKeyOut> {
    return this.client.request<ApiKeyOut>(`/auth/keys/${keyId}`, {
      method: "DELETE",
    });
  }

  /**
   * Get current user information
   */
  async getCurrentUser(): Promise<CurrentUserOut> {
    return this.client.request<CurrentUserOut>("/auth/me");
  }
}
