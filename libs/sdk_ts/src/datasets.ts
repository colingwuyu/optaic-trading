
import { type UUID } from "./index.js";

export interface DatasetInstance {
  id: UUID;
  name: string;
  type: "DatasetInstance";
  status: string;
  freshness_status: string;
  last_data_date?: string | null;
  row_count?: number | null;
  pipeline_instance_id: UUID;
  store_instance_id: UUID;
  accessor_instance_id: UUID;
}

export interface DatasetPreview {
  columns: string[];
  data: Array<Record<string, unknown>>;
  row_count: number;
  truncated: boolean;
}

export interface DatasetCreate {
  name: string;
  parent_id: UUID;
  pipeline_instance_id: UUID;
  store_instance_id: UUID;
  accessor_instance_id: UUID;
  freshness_status?: string;
}

export interface DatasetFilters {
  parent_id?: UUID;
  freshness_status?: string;
  limit?: number;
}

export interface IApiClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class DatasetsClient {
  private client: IApiClient;

  constructor(client: IApiClient) {
    this.client = client;
  }

  create(payload: DatasetCreate): Promise<DatasetInstance> {
    return this.client.request<DatasetInstance>("/datasets", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  list(params?: DatasetFilters): Promise<DatasetInstance[]> {
    const search = new URLSearchParams();
    if (params?.parent_id) search.set("parent_id", params.parent_id);
    if (params?.freshness_status) search.set("freshness_status", params.freshness_status);
    if (params?.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return this.client.request<DatasetInstance[]>(`/datasets${query ? `?${query}` : ""}`);
  }

  get(datasetId: UUID): Promise<DatasetInstance> {
    return this.client.request<DatasetInstance>(`/datasets/${datasetId}`);
  }

  status(datasetId: UUID): Promise<{ status: string; freshness_status: string; last_data_date?: string }> {
    return this.client.request<{ status: string; freshness_status: string; last_data_date?: string }>(
      `/datasets/${datasetId}/status`
    );
  }

  preview(
    datasetId: UUID,
    params?: { start_date?: string; end_date?: string; as_of_date?: string; limit?: number }
  ): Promise<DatasetPreview> {
    return this.client.request<DatasetPreview>(`/datasets/${datasetId}/preview`, {
      method: "POST",
      body: JSON.stringify(params || {}),
    });
  }

  refresh(datasetId: UUID): Promise<{ id: UUID; status: string; message: string }> {
    return this.client.request<{ id: UUID; status: string; message: string }>(
      `/datasets/${datasetId}/refresh`,
      { method: "POST" }
    );
  }
}
