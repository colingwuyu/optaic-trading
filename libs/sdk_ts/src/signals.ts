
import { type UUID } from "./index.js";
import { type IApiClient } from "./datasets.js";

export interface SignalInstance {
  id: UUID;
  name: string;
  spec: {
    min_value: number;
    max_value: number;
    allow_nan: boolean;
    neutral_value: number;
  };
  status: "staging" | "official";
}

export interface SignalRegister {
  dataset_id: UUID;
  name: string;
  parent_id?: UUID;
  min_value?: number;
  max_value?: number;
  allow_nan?: boolean;
  neutral_value?: number;
}

export interface SignalValidation {
  id: UUID;
  valid: boolean;
  issues: string[];
}

export class SignalsClient {
  private client: IApiClient;

  constructor(client: IApiClient) {
    this.client = client;
  }

  list(params?: { parent_id?: UUID; status?: string; limit?: number }): Promise<SignalInstance[]> {
    const search = new URLSearchParams();
    if (params?.parent_id) search.set("parent_id", params.parent_id);
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return this.client.request<SignalInstance[]>(`/signals${query ? `?${query}` : ""}`);
  }

  register(payload: SignalRegister): Promise<SignalInstance> {
    return this.client.request<SignalInstance>("/signals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  get(signalId: UUID): Promise<SignalInstance> {
    return this.client.request<SignalInstance>(`/signals/${signalId}`);
  }

  validate(signalId: UUID): Promise<SignalValidation> {
    return this.client.request<SignalValidation>(`/signals/${signalId}/validate`, {
      method: "POST",
    });
  }

  promote(signalId: UUID): Promise<SignalInstance> {
    return this.client.request<SignalInstance>(`/signals/${signalId}/promote`, {
      method: "POST",
    });
  }
}
