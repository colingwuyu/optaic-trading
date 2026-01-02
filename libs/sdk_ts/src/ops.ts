
import { type UUID } from "./index.js";
import { type IApiClient } from "./datasets.js";

export interface Operator {
  name: string;
  category: string;
  arity: number;
  description: string;
}

export interface EvaluationResult {
  columns: string[];
  data: Array<Record<string, unknown>>;
  row_count: number;
  truncated: boolean;
}

export class OpsClient {
  private client: IApiClient;

  constructor(client: IApiClient) {
    this.client = client;
  }

  list(params?: { category?: string }): Promise<{ operators: Operator[]; count: number }> {
    const search = new URLSearchParams();
    if (params?.category) search.set("category", params.category);
    const query = search.toString();
    return this.client.request<{ operators: Operator[]; count: number }>(`/ops${query ? `?${query}` : ""}`);
  }

  get(name: string): Promise<Operator> {
    return this.client.request<Operator>(`/ops/${name}`);
  }

  evaluate(
    expression: string,
    context: Record<string, UUID>,
    params?: { start_date?: string; end_date?: string; limit?: number }
  ): Promise<EvaluationResult> {
    return this.client.request<EvaluationResult>("/ops/evaluate", {
      method: "POST",
      body: JSON.stringify({
        expression,
        context,
        ...params,
      }),
    });
  }
}
