/**
 * RBAC client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  RoleBindingOut,
  EffectivePermissions,
} from "./types/index.js";

export interface IRbacClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class RbacClient {
  constructor(private client: IRbacClient) {}

  /**
   * Grant a role to a principal on a resource
   */
  async grant(
    principalId: UUID,
    roleName: string,
    scopeResourceId: UUID
  ): Promise<RoleBindingOut> {
    return this.client.request<RoleBindingOut>("/rbac/grants", {
      method: "POST",
      body: JSON.stringify({
        principal_id: principalId,
        role_name: roleName,
        scope_resource_id: scopeResourceId,
      }),
    });
  }

  /**
   * Revoke a role binding
   */
  async revoke(bindingId: UUID): Promise<RoleBindingOut> {
    return this.client.request<RoleBindingOut>(`/rbac/grants/${bindingId}`, {
      method: "DELETE",
    });
  }

  /**
   * List role bindings for a resource
   */
  async listGrants(
    resourceId: UUID,
    principalId?: UUID
  ): Promise<RoleBindingOut[]> {
    const search = new URLSearchParams({ resource_id: resourceId });
    if (principalId) search.set("principal_id", principalId);
    return this.client.request<RoleBindingOut[]>(`/rbac/grants?${search}`);
  }

  /**
   * Get effective permissions for a principal on a resource
   */
  async effective(
    resourceId: UUID,
    principalId?: UUID
  ): Promise<EffectivePermissions> {
    const search = new URLSearchParams({ resource_id: resourceId });
    if (principalId) search.set("principal_id", principalId);
    return this.client.request<EffectivePermissions>(`/rbac/effective?${search}`);
  }
}
