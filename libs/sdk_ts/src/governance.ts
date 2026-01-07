/**
 * Governance client for OptAIC TypeScript SDK
 *
 * Provides SDK methods for:
 * - Copy (reference): Same artifact, no RBAC change
 * - Branch: Copy files, actor=owner, source_owner=viewer
 * - Transfer: Request/accept workflow
 * - Promote: To staging, approval-based auto-move to official
 * - Merge: Branch artifact replaces ancestor
 * - Lineage: Query resource derivation history
 */

import type {
  UUID,
  GovernanceOperationOut,
  TransferRequestOut,
  LineageOut,
} from "./types/index.js";

export interface IGovernanceClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class GovernanceClient {
  constructor(private client: IGovernanceClient) {}

  // =========================================================================
  // Core Governance Operations
  // =========================================================================

  /**
   * Copy a resource by reference (no file copy)
   */
  async copy(
    resourceId: UUID,
    targetParentId: UUID,
    name?: string
  ): Promise<GovernanceOperationOut> {
    const payload: Record<string, unknown> = {
      target_parent_id: targetParentId,
    };
    if (name) payload.name = name;
    return this.client.request<GovernanceOperationOut>(
      `/governance/resources/${resourceId}/copy`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Branch a resource with file copy
   */
  async branch(
    resourceId: UUID,
    targetParentId: UUID,
    name?: string
  ): Promise<GovernanceOperationOut> {
    const payload: Record<string, unknown> = {
      target_parent_id: targetParentId,
    };
    if (name) payload.name = name;
    return this.client.request<GovernanceOperationOut>(
      `/governance/resources/${resourceId}/branch`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Promote a resource to a team's staging subspace
   */
  async promote(
    resourceId: UUID,
    targetSpaceId: UUID,
    teamPrincipalId: UUID,
    name?: string
  ): Promise<GovernanceOperationOut> {
    const payload: Record<string, unknown> = {
      target_space_id: targetSpaceId,
      team_principal_id: teamPrincipalId,
    };
    if (name) payload.name = name;
    return this.client.request<GovernanceOperationOut>(
      `/governance/resources/${resourceId}/promote`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Merge a branch back to its ancestor
   */
  async merge(sourceId: UUID, targetId: UUID): Promise<GovernanceOperationOut> {
    return this.client.request<GovernanceOperationOut>(
      `/governance/resources/${sourceId}/merge`,
      {
        method: "POST",
        body: JSON.stringify({ target_id: targetId }),
      }
    );
  }

  // =========================================================================
  // Transfer Request Workflow
  // =========================================================================

  /**
   * Create a transfer request for a resource
   */
  async createTransferRequest(
    resourceId: UUID,
    recipientId: UUID,
    message?: string
  ): Promise<TransferRequestOut> {
    const payload: Record<string, unknown> = {
      recipient_id: recipientId,
    };
    if (message) payload.message = message;
    return this.client.request<TransferRequestOut>(
      `/governance/resources/${resourceId}/transfer-request`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Accept a transfer request
   */
  async acceptTransfer(
    transferRequestId: UUID,
    destinationProjectId: UUID,
    responseMessage?: string
  ): Promise<TransferRequestOut> {
    const payload: Record<string, unknown> = {
      destination_project_id: destinationProjectId,
    };
    if (responseMessage) payload.response_message = responseMessage;
    return this.client.request<TransferRequestOut>(
      `/governance/transfers/${transferRequestId}/accept`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Reject a transfer request
   */
  async rejectTransfer(
    transferRequestId: UUID,
    responseMessage?: string
  ): Promise<TransferRequestOut> {
    const payload: Record<string, unknown> = {};
    if (responseMessage) payload.response_message = responseMessage;
    return this.client.request<TransferRequestOut>(
      `/governance/transfers/${transferRequestId}/reject`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Cancel a transfer request
   */
  async cancelTransfer(transferRequestId: UUID): Promise<TransferRequestOut> {
    return this.client.request<TransferRequestOut>(
      `/governance/transfers/${transferRequestId}/cancel`,
      {
        method: "POST",
      }
    );
  }

  /**
   * Direct transfer (legacy, use request/accept workflow)
   * @deprecated Use createTransferRequest + acceptTransfer instead
   */
  async transfer(
    resourceId: UUID,
    targetOwnerId: UUID
  ): Promise<GovernanceOperationOut> {
    return this.client.request<GovernanceOperationOut>(
      `/governance/resources/${resourceId}/transfer`,
      {
        method: "POST",
        body: JSON.stringify({ target_owner_id: targetOwnerId }),
      }
    );
  }

  // =========================================================================
  // Promotion Approval
  // =========================================================================

  /**
   * Approve a promotion request
   */
  async approvePromotion(
    promotionRequestId: UUID,
    comment?: string
  ): Promise<{ approval_count: number; status: string }> {
    const payload: Record<string, unknown> = {};
    if (comment) payload.comment = comment;
    return this.client.request<{ approval_count: number; status: string }>(
      `/governance/promotions/${promotionRequestId}/approve`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  // =========================================================================
  // Lineage Queries
  // =========================================================================

  /**
   * Get resource lineage (ancestors or descendants)
   */
  async getLineage(
    resourceId: UUID,
    params?: {
      direction?: "upstream" | "downstream";
      edgeTypes?: string[];
      maxDepth?: number;
    }
  ): Promise<LineageOut> {
    const search = new URLSearchParams();
    if (params?.direction) search.set("direction", params.direction);
    if (params?.edgeTypes) search.set("edge_types", params.edgeTypes.join(","));
    if (params?.maxDepth) search.set("max_depth", String(params.maxDepth));
    const query = search.toString();
    return this.client.request<LineageOut>(
      `/governance/resources/${resourceId}/lineage${query ? `?${query}` : ""}`
    );
  }
}
