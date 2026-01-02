
import { type UUID } from "./index.js";
import { type IApiClient } from "./datasets.js";

export interface PipelineDefinition {
  id: UUID;
  name: string;
  code_ref: string;
  category: string;
  status: "draft" | "active";
}

export interface PipelineInstance {
  id: UUID;
  name: string;
  definition_id: UUID;
  status: "idle" | "running";
}

export interface PipelineSubmit {
  name: string;
  code_ref: string;
  parent_id: UUID;
  category?: string;
  interface_spec?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  parameters_schema?: Record<string, unknown>;
  guardrail_contracts?: Array<Record<string, unknown>>;
}

export interface PipelineInstanceCreate {
  name: string;
  definition_id: UUID;
  parent_id: UUID;
  config?: Record<string, unknown>;
  schedule?: Record<string, unknown>;
}

export class PipelinesClient {
  private client: IApiClient;

  constructor(client: IApiClient) {
    this.client = client;
  }

  submitDefinition(payload: PipelineSubmit): Promise<PipelineDefinition> {
    return this.client.request<PipelineDefinition>("/pipelines/definitions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  deployDefinition(definitionId: UUID): Promise<PipelineDefinition> {
    return this.client.request<PipelineDefinition>(`/pipelines/definitions/${definitionId}/deploy`, {
      method: "POST",
    });
  }

  listDefinitions(params?: { category?: string; status?: string; limit?: number }): Promise<PipelineDefinition[]> {
    const search = new URLSearchParams();
    if (params?.category) search.set("category", params.category);
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return this.client.request<PipelineDefinition[]>(`/pipelines/definitions${query ? `?${query}` : ""}`);
  }

  createInstance(payload: PipelineInstanceCreate): Promise<PipelineInstance> {
    return this.client.request<PipelineInstance>("/pipelines/instances", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  listInstances(params?: { parent_id?: UUID; status?: string; limit?: number }): Promise<PipelineInstance[]> {
    const search = new URLSearchParams();
    if (params?.parent_id) search.set("parent_id", params.parent_id);
    if (params?.status) search.set("status", params.status);
    if (params?.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return this.client.request<PipelineInstance[]>(`/pipelines/instances${query ? `?${query}` : ""}`);
  }

  run(instanceId: UUID): Promise<{ run_id: UUID; status: string }> {
    return this.client.request<{ run_id: UUID; status: string }>(`/pipelines/instances/${instanceId}/run`, {
      method: "POST",
    });
  }
}
