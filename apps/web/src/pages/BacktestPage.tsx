import { useState } from "react";
import {
  PlayCircle,
  Plus,
  CheckCircle,
  Clock,
  XCircle,
  TrendingUp,
  TrendingDown,
  Activity,
  AlertTriangle,
  Calendar,
  Hash,
  Percent,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { cn, formatDate, formatNumber, formatPercentage } from "../lib/utils";
import {
  useBacktestStore,
  useSelectedRun,
  type BacktestRun,
} from "../stores/backtest";

function KpiCard({
  label,
  value,
  icon: Icon,
  color,
  trend,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  color: string;
  trend?: "up" | "down";
}) {
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-slate-400">{label}</span>
        <Icon className={cn("w-4 h-4", color)} />
      </div>
      <div className="flex items-center gap-2">
        <span className={cn("text-2xl font-mono font-semibold", color)}>
          {value}
        </span>
        {trend && (
          trend === "up" ? (
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          ) : (
            <TrendingDown className="w-4 h-4 text-red-400" />
          )
        )}
      </div>
    </div>
  );
}

function RunSelector({ runs, selectedId, onSelect }: {
  runs: BacktestRun[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const getStatusIcon = (status: BacktestRun["status"]) => {
    switch (status) {
      case "completed":
        return <CheckCircle className="w-4 h-4 text-emerald-400" />;
      case "running":
        return <Clock className="w-4 h-4 text-blue-400 animate-pulse" />;
      case "failed":
        return <XCircle className="w-4 h-4 text-red-400" />;
      default:
        return <Clock className="w-4 h-4 text-slate-400" />;
    }
  };

  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <button
          key={run.id}
          onClick={() => onSelect(run.id)}
          className={cn(
            "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors",
            selectedId === run.id
              ? "bg-indigo-600/20 border border-indigo-500/50"
              : "hover:bg-slate-800/50"
          )}
        >
          {getStatusIcon(run.status)}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">{run.name}</p>
            <p className="text-xs text-slate-500">{formatDate(run.startedAt)}</p>
          </div>
        </button>
      ))}
    </div>
  );
}

function OverviewTab() {
  const run = useSelectedRun();

  if (!run?.results) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500">
        <div className="text-center">
          <Activity className="w-12 h-12 mx-auto mb-4 animate-pulse" />
          <p>Backtest in progress...</p>
        </div>
      </div>
    );
  }

  const { results } = run;

  return (
    <div className="space-y-6">
      {/* KPI Grid */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          label="Sharpe Ratio"
          value={formatNumber(results.sharpeRatio)}
          icon={Activity}
          color="text-indigo-400"
        />
        <KpiCard
          label="Total Return"
          value={formatPercentage(results.totalReturn)}
          icon={TrendingUp}
          color={results.totalReturn >= 0 ? "text-emerald-400" : "text-red-400"}
          trend={results.totalReturn >= 0 ? "up" : "down"}
        />
        <KpiCard
          label="Volatility"
          value={formatPercentage(results.volatility)}
          icon={Activity}
          color="text-amber-400"
        />
        <KpiCard
          label="Max Drawdown"
          value={formatPercentage(results.maxDrawdown)}
          icon={AlertTriangle}
          color="text-rose-400"
        />
      </div>

      {/* Equity Curve Chart */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
        <h3 className="text-sm font-medium text-slate-400 mb-4">Equity Curve</h3>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={results.equityCurve}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="date"
                stroke="#64748b"
                fontSize={12}
                tickFormatter={(val) => {
                  const d = new Date(val);
                  return d.toLocaleDateString("en-US", { month: "short" });
                }}
              />
              <YAxis
                stroke="#64748b"
                fontSize={12}
                tickFormatter={(val) => `$${val.toFixed(0)}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                }}
                labelStyle={{ color: "#94a3b8" }}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, "Value"]}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#6366f1"
                strokeWidth={2}
                fill="url(#equityGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Additional Stats */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Hash className="w-4 h-4 text-slate-400" />
            <span className="text-sm text-slate-400">Total Trades</span>
          </div>
          <span className="text-xl font-mono text-white">{results.trades}</span>
        </div>
        <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Percent className="w-4 h-4 text-slate-400" />
            <span className="text-sm text-slate-400">Win Rate</span>
          </div>
          <span className="text-xl font-mono text-white">
            {formatPercentage(results.winRate)}
          </span>
        </div>
      </div>
    </div>
  );
}

function ModelsTab() {
  const { modelVersions } = useBacktestStore();

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-slate-400 mb-4">Model Versions</h3>
      {modelVersions.map((version) => (
        <div
          key={version.id}
          className="bg-slate-900/50 border border-slate-800 rounded-lg p-4"
        >
          <div className="flex items-start justify-between mb-3">
            <div>
              <h4 className="font-medium text-white">{version.modelId}</h4>
              <p className="text-xs text-slate-500 flex items-center gap-1 mt-1">
                <Calendar className="w-3 h-3" />
                Recalibrated {formatDate(version.recalibrationDate)}
              </p>
            </div>
            <span className="px-2 py-1 bg-indigo-500/10 text-indigo-400 rounded text-xs font-medium">
              R² {formatPercentage(version.globalR2)}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-500">Calibration Window</span>
              <p className="text-white">{version.calibrationWindowDays} days</p>
            </div>
            <div>
              <span className="text-slate-500">Signal Count</span>
              <p className="text-white">{version.signalCount}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReplayTab() {
  const { replayDate, setReplayDate } = useBacktestStore();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <label className="text-sm text-slate-400">Replay Date</label>
        <input
          type="date"
          value={replayDate}
          onChange={(e) => setReplayDate(e.target.value)}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
      <div className="flex items-center justify-center h-48 bg-slate-900/50 border border-slate-800 rounded-lg text-slate-500">
        <div className="text-center">
          <Calendar className="w-12 h-12 mx-auto mb-4" />
          <p>Daily replay visualization coming soon</p>
          <p className="text-sm mt-1">Select a date to view historical positions</p>
        </div>
      </div>
    </div>
  );
}

export function BacktestPage() {
  const { runs, selectedRunId, activeTab, selectRun, setActiveTab, setIsConfigOpen } =
    useBacktestStore();
  const selectedRun = useSelectedRun();

  const tabs = [
    { id: "overview" as const, label: "Overview & Risk" },
    { id: "models" as const, label: "Model Versions" },
    { id: "replay" as const, label: "Daily Replay" },
  ];

  return (
    <div className="flex h-full">
      {/* Sidebar - Run List */}
      <aside className="w-72 flex-shrink-0 border-r border-slate-800 overflow-hidden flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <button
            onClick={() => setIsConfigOpen(true)}
            className="flex items-center justify-center gap-2 w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>New Backtest</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <RunSelector runs={runs} selectedId={selectedRunId} onSelect={selectRun} />
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="flex-shrink-0 px-6 py-4 border-b border-slate-800">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-purple-500/10 rounded-lg">
              <PlayCircle className="w-6 h-6 text-purple-400" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-white">Backtest Engine</h1>
              <p className="text-sm text-slate-400">
                Configure, run, and analyze historical simulations.
              </p>
            </div>
          </div>

          {selectedRun && (
            <>
              <h2 className="text-lg font-medium text-white mb-4">{selectedRun.name}</h2>
              {/* Tabs */}
              <div className="flex gap-1 bg-slate-800/50 p-1 rounded-lg w-fit">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      "px-4 py-2 rounded-md text-sm transition-colors",
                      activeTab === tab.id
                        ? "bg-indigo-600 text-white"
                        : "text-slate-400 hover:text-white"
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </header>

        {/* Tab Content */}
        <main className="flex-1 overflow-y-auto p-6">
          {!selectedRun ? (
            <div className="flex items-center justify-center h-64 text-slate-500">
              <div className="text-center">
                <PlayCircle className="w-12 h-12 mx-auto mb-4" />
                <p>Select a backtest run to view results</p>
                <p className="text-sm mt-1">Or create a new backtest</p>
              </div>
            </div>
          ) : activeTab === "overview" ? (
            <OverviewTab />
          ) : activeTab === "models" ? (
            <ModelsTab />
          ) : (
            <ReplayTab />
          )}
        </main>
      </div>
    </div>
  );
}
