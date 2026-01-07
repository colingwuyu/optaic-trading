/**
 * Subscriptions client for OptAIC TypeScript SDK
 */

import type { UUID, SubscriptionOut, SubscriptionCreate } from "./types/index.js";

export interface ISubscriptionsClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class SubscriptionsClient {
  constructor(private client: ISubscriptionsClient) {}

  /**
   * Create a subscription to a resource
   */
  async create(payload: SubscriptionCreate): Promise<SubscriptionOut> {
    return this.client.request<SubscriptionOut>("/subscriptions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Revoke (soft-delete) a subscription
   */
  async revoke(subscriptionId: UUID): Promise<SubscriptionOut> {
    return this.client.request<SubscriptionOut>(
      `/subscriptions/${subscriptionId}`,
      {
        method: "DELETE",
      }
    );
  }

  /**
   * List active subscriptions for the current user
   */
  async list(): Promise<SubscriptionOut[]> {
    return this.client.request<SubscriptionOut[]>("/subscriptions");
  }
}
