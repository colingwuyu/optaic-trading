import { useEffect, useMemo, useState } from "react";

import type {
  RuntimeInfo,
  UpgradePlan,
  UpgradeStart,
} from "@sdk";
import { Button } from "@/components/ui/button";
import { useApiClient } from "@/services/api";

export const SystemUpdatesPanel = () => {
  const api = useApiClient();
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [plan, setPlan] = useState<UpgradePlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [savingChannel, setSavingChannel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const loadRuntime = async () => {
    if (!api) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.system.getRuntime();
      setRuntime(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const checkUpdates = async (runtimeInfo?: RuntimeInfo) => {
    if (!api) return null;
    setChecking(true);
    setError(null);
    try {
      const effectiveRuntime = runtimeInfo ?? runtime ?? (await api.system.getRuntime());
      const data = await api.system.getUpgradePlan({
        with_redis: effectiveRuntime.with_redis,
        check_package_updates: true,
      });
      setPlan(data);
      setRuntime(effectiveRuntime);
      return data;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setChecking(false);
    }
  };

  const pollRuntime = async () => {
    if (!api) return;
    const pollUntil = Date.now() + 180000;
    while (Date.now() < pollUntil) {
      try {
        const data = await api.system.getRuntime();
        setStatus("Server restarted.");
        setRuntime(data);
        await checkUpdates(data);
        return;
      } catch {
        // ignore while restarting
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    setStatus("Restart timed out. Refresh to retry.");
  };

  const startUpgrade = async () => {
    if (!api) return;
    let planData = plan;
    if (!planData) {
      planData = await checkUpdates();
    }
    if (!planData) {
      setError("No upgrade plan available yet.");
      return;
    }
    let effectiveRuntime = runtime;
    if (!effectiveRuntime) {
      try {
        effectiveRuntime = await api.system.getRuntime();
        setRuntime(effectiveRuntime);
      } catch {
        effectiveRuntime = null;
      }
    }
    const hasPackageUpdate = Boolean(planData.package_update?.has_update);
    const hasInfraChanges = Boolean(
      planData && (planData.db_migration_needed || planData.infra_plan.length > 0),
    );
    if (!hasPackageUpdate && !hasInfraChanges) {
      setStatus("No updates available.");
      return;
    }
    if (
      !window.confirm(
        "Upgrade now? The server will restart and reconnect automatically.",
      )
    ) {
      return;
    }

    setUpgrading(true);
    setError(null);
    setStatus("Upgrading... server will restart.");
    const applyPackageUpdate = Boolean(planData.package_update?.has_update);
    try {
      const result: UpgradeStart = await api.system.startUpgrade({
        with_redis: effectiveRuntime?.with_redis ?? false,
        apply_package_update: applyPackageUpdate,
        restart: true,
      });
      if (result.message) {
        setStatus(result.message);
      }
      if (result.will_restart) {
        await pollRuntime();
      } else {
        setStatus(`Upgrade scheduled (${result.status}).`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUpgrading(false);
    }
  };

  const updateChannel = async (nextChannel: string) => {
    if (!api) {
      setError("API client not available.");
      return;
    }
    setSavingChannel(true);
    setError(null);
    try {
      const payload = await api.system.updateChannel(nextChannel);
      setRuntime((prev) =>
        prev
          ? {
              ...prev,
              channel: payload.channel,
              package_index_url: payload.package_index_url ?? prev.package_index_url,
            }
          : {
              version: "unknown",
              tools: {},
              centrifugo_engine: "memory",
              with_redis: false,
              channel: payload.channel,
              package_index_url: payload.package_index_url ?? null,
            },
      );
      await checkUpdates();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingChannel(false);
    }
  };

  useEffect(() => {
    if (api) {
      void loadRuntime();
    }
  }, [api]);

  const {
    centrifugoVersion,
    redisStatus,
    dbSchema,
    currentVersion,
    latestVersion,
    currentChannel,
  } = useMemo(() => {
    const tools = runtime?.tools ?? {};
    const centrifugo = tools.centrifugo as Record<string, unknown> | undefined;
    const redis = tools.redis as Record<string, unknown> | undefined;
    const centrifugoVersion =
      typeof centrifugo?.version === "string" ? centrifugo.version : "unknown";
    const redisEnabled = Boolean(runtime?.with_redis);
    const redisVersion =
      typeof redis?.version === "string" ? redis.version : null;
    const redisMode =
      typeof redis?.mode === "string"
        ? redis.mode
        : redis?.enabled === false
        ? "disabled"
        : redisEnabled
        ? "embedded"
        : "disabled";
    const redisStatus = redisEnabled
      ? `enabled (${redisMode}${redisVersion ? `, ${redisVersion}` : ""})`
      : "disabled";
    const dbSchema = runtime?.db_alembic_head
      ? `${runtime.db_dialect ?? "db"}:${runtime.db_alembic_head}`
      : `${runtime?.db_dialect ?? "db"}:unknown`;
    const currentVersion = runtime?.version ?? "unknown";
    const latestVersion = plan?.package_update?.latest_version ?? currentVersion;
    const currentChannel = runtime?.channel ?? "prod";
    return {
      centrifugoVersion,
      redisStatus,
      dbSchema,
      currentVersion,
      latestVersion,
      currentChannel,
    };
  }, [runtime, plan]);

  const hasPackageUpdate = Boolean(plan?.package_update?.has_update);
  const hasInfraChanges = Boolean(
    plan && (plan.db_migration_needed || plan.infra_plan.length > 0),
  );
  const canUpgrade = Boolean(plan) && (hasPackageUpdate || hasInfraChanges);

  return (
    <div className="space-y-4 rounded-2xl border border-fog-200 bg-white p-6 shadow-sm">
      <div>
        <h3 className="font-display text-xl text-ink-900">System Updates</h3>
        <p className="text-sm text-ink-700">Monitor versions and apply upgrades.</p>
      </div>
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-600">
          {error}
        </div>
      )}
      {runtime ? (
        <div className="grid gap-2 text-sm text-ink-700">
          <div>
            OptAIC package: <span className="font-medium">{currentVersion}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-ink-700">Channel:</span>
            <select
              className="rounded-md border border-fog-200 bg-white px-2 py-1 text-sm text-ink-800"
              value={currentChannel}
              onChange={(event) => void updateChannel(event.target.value)}
              disabled={savingChannel || upgrading}
            >
              <option value="prod">prod</option>
              <option value="uat">uat</option>
              <option value="staging">staging</option>
            </select>
            {runtime.package_index_url && (
              <span className="text-xs text-ink-500">
                {runtime.package_index_url}
              </span>
            )}
          </div>
          <div>
            DB schema: <span className="font-medium">{dbSchema}</span>
          </div>
          <div>
            Centrifugo:{" "}
            <span className="font-medium">{centrifugoVersion}</span> · Engine:{" "}
            <span className="font-medium">{runtime.centrifugo_engine}</span>
          </div>
          <div>
            Redis: <span className="font-medium">{redisStatus}</span>
          </div>
          {runtime.upgrade_status?.status && (
            <div>
              Upgrade status:{" "}
              <span className="font-medium">{runtime.upgrade_status.status}</span>
            </div>
          )}
          {runtime.last_upgrade_at && (
            <div className="text-xs text-ink-500">
              Last upgrade: {runtime.last_upgrade_at}
            </div>
          )}
          {runtime.upgrade_status?.last_error && (
            <div className="text-xs text-red-600">
              Last error: {runtime.upgrade_status.last_error}
            </div>
          )}
        </div>
      ) : (
        <div className="text-sm text-ink-600">
          {loading ? "Loading runtime info..." : "Runtime info unavailable."}
        </div>
      )}
      {plan ? (
        <div className="space-y-2 text-sm text-ink-700">
          <div>
            Latest package: <span className="font-medium">{latestVersion}</span>
            {hasPackageUpdate ? " (update available)" : " (up to date)"}
          </div>
          {plan.package_update?.message && (
            <div className="text-xs text-ink-500">{plan.package_update.message}</div>
          )}
          {plan.warnings?.length ? (
            <div className="text-xs text-ink-500">{plan.warnings.join(" ")}</div>
          ) : null}
          <div className="text-xs text-ink-500">
            Infra updates:{" "}
            {plan.infra_plan.length
              ? plan.infra_plan.map((item) => `${item.tool} ${item.version}`).join(", ")
              : "none"}{" "}
            · DB migration needed: {plan.db_migration_needed ? "yes" : "no"}
          </div>
        </div>
      ) : (
        <div className="text-sm text-ink-600">
          {checking ? "Checking for updates..." : "No update check yet."}
        </div>
      )}
      {status && <div className="text-xs text-ink-600">{status}</div>}
      {upgrading && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700">
          Upgrading... server will restart.
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void checkUpdates()}
          disabled={loading || checking || upgrading}
        >
          {checking ? "Checking..." : "Check for updates"}
        </Button>
        <Button
          size="sm"
          onClick={startUpgrade}
          disabled={!canUpgrade || upgrading}
        >
          {upgrading ? "Upgrading..." : "Upgrade now"}
        </Button>
      </div>
    </div>
  );
};
