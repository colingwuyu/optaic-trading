/**
 * System client for OptAIC TypeScript SDK
 * Handles system runtime info, upgrades, and channel management
 */

export interface RuntimeInfo {
  version: string;
  channel?: string | null;
  package_index_url?: string | null;
  db_dialect?: string | null;
  db_alembic_head?: string | null;
  tools: Record<string, unknown>;
  centrifugo_engine: string;
  with_redis: boolean;
  last_upgrade_at?: string | null;
  upgrade_status?: {
    status?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    last_error?: string | null;
  };
}

export interface PackageUpdate {
  package: string;
  current_version: string;
  latest_version: string;
  has_update: boolean;
  source: string;
  index_url?: string | null;
  checked_at: string;
  message?: string | null;
}

export interface InfraAction {
  tool: string;
  version: string;
  asset_url: string;
  asset_sha256: string;
}

export interface UpgradePlan {
  package_update?: PackageUpdate | null;
  infra_plan: InfraAction[];
  db_migration_needed: boolean;
  warnings: string[];
}

export interface UpgradeStart {
  status: string;
  job_path?: string | null;
  message?: string | null;
  will_restart: boolean;
}

export interface ChannelUpdate {
  channel: string;
  package_index_url?: string | null;
}

export interface ISystemClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class SystemClient {
  constructor(private client: ISystemClient) {}

  /**
   * Get runtime information
   */
  async getRuntime(): Promise<RuntimeInfo> {
    return this.client.request<RuntimeInfo>("/system/runtime");
  }

  /**
   * Get upgrade plan
   */
  async getUpgradePlan(params: {
    with_redis: boolean;
    check_package_updates?: boolean;
  }): Promise<UpgradePlan> {
    return this.client.request<UpgradePlan>("/system/upgrade/plan", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Start upgrade process
   */
  async startUpgrade(params: {
    with_redis: boolean;
    apply_package_update?: boolean;
    restart?: boolean;
  }): Promise<UpgradeStart> {
    return this.client.request<UpgradeStart>("/system/upgrade/start", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /**
   * Update release channel
   */
  async updateChannel(channel: string): Promise<ChannelUpdate> {
    return this.client.request<ChannelUpdate>("/system/channel", {
      method: "POST",
      body: JSON.stringify({ channel }),
    });
  }
}
