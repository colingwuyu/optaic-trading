
import { type UUID } from "./index.js";
import { type IApiClient } from "./datasets.js";

export interface Experiment {
  id: UUID;
  name: string;
  expression: string;
  input_datasets: Record<string, UUID>;
  description?: string;
  created_at: string;
}

export interface ExperimentCreate {
  name: string;
  expression: string;
  parent_id: UUID;
  input_datasets?: Record<string, UUID>;
  description?: string;
}

export interface ExperimentRunResult {
  success: boolean;
  columns: string[];
  data: Array<Record<string, unknown>>;
  row_count: number;
}

export interface ExperimentUpdate {
  expression?: string;
  input_datasets?: Record<string, UUID>;
}

export class ExperimentsClient {
  private client: IApiClient;

  constructor(client: IApiClient) {
    this.client = client;
  }

  create(payload: ExperimentCreate): Promise<Experiment> {
    return this.client.request<Experiment>("/experiments", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  list(params?: { parent_id?: UUID; limit?: number }): Promise<Experiment[]> {
    const search = new URLSearchParams();
    if (params?.parent_id) search.set("parent_id", params.parent_id);
    if (params?.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return this.client.request<Experiment[]>(`/experiments${query ? `?${query}` : ""}`);
  }

  get(experimentId: UUID): Promise<Experiment> {
    return this.client.request<Experiment>(`/experiments/${experimentId}`);
  }

  run(
    experimentId: UUID,
    params?: { start_date?: string; end_date?: string; limit?: number }
  ): Promise<ExperimentRunResult> {
    return this.client.request<ExperimentRunResult>(`/experiments/${experimentId}/run`, {
      method: "POST",
      body: JSON.stringify(params || {}),
    });
  }

  update(experimentId: UUID, payload: ExperimentUpdate): Promise<Experiment> {
    return this.client.request<Experiment>(`/experiments/${experimentId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  saveAsMacro(experimentId: UUID, macroName?: string): Promise<{ id: UUID; name: string }> {
    const search = new URLSearchParams();
    if (macroName) search.set("macro_name", macroName);
    const query = search.toString();
    return this.client.request<{ id: UUID; name: string }>(
      `/experiments/${experimentId}/save-as-macro${query ? `?${query}` : ""}`,
      { method: "POST" }
    );
  }
}
