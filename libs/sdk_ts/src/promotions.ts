/**
 * Promotions client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  PromotionCreate,
  PromotionRequestOut,
  PromotionApprovalIn,
  PromotionApprovalOut,
  PromotionExecuteOut,
} from "./types/index.js";

export interface IPromotionsClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class PromotionsClient {
  constructor(private client: IPromotionsClient) {}

  /**
   * Create a promotion request
   */
  async create(payload: PromotionCreate): Promise<PromotionRequestOut> {
    return this.client.request<PromotionRequestOut>("/promotions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get a promotion request by ID
   */
  async get(promotionId: UUID): Promise<PromotionRequestOut> {
    return this.client.request<PromotionRequestOut>(
      `/promotions/${promotionId}`
    );
  }

  /**
   * List promotion requests
   */
  async list(params?: {
    status?: string;
    limit?: number;
    cursor?: string;
  }): Promise<{ items: PromotionRequestOut[]; next_cursor?: string | null }> {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<{
      items: PromotionRequestOut[];
      next_cursor?: string | null;
    }>(`/promotions${query ? `?${query}` : ""}`);
  }

  /**
   * Approve or reject a promotion request
   */
  async approve(
    promotionId: UUID,
    payload: PromotionApprovalIn
  ): Promise<PromotionApprovalOut> {
    return this.client.request<PromotionApprovalOut>(
      `/promotions/${promotionId}/approve`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Execute a promotion request (move/copy to target)
   */
  async execute(promotionId: UUID): Promise<PromotionExecuteOut> {
    return this.client.request<PromotionExecuteOut>(
      `/promotions/${promotionId}/execute`,
      {
        method: "POST",
      }
    );
  }
}
