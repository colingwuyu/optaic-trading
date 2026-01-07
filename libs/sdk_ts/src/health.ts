/**
 * Health client for OptAIC TypeScript SDK
 */

import type { HealthOut } from "./types/index.js";

export interface IHealthClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class HealthClient {
  constructor(private client: IHealthClient) {}

  /**
   * Get health status
   */
  async check(): Promise<HealthOut> {
    return this.client.request<HealthOut>("/healthz");
  }

  /**
   * Readiness probe
   */
  async ready(): Promise<HealthOut> {
    return this.client.request<HealthOut>("/readyz");
  }

  /**
   * Liveness probe
   */
  async live(): Promise<HealthOut> {
    return this.client.request<HealthOut>("/livez");
  }
}
