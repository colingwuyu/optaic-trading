import { useState } from "react";
import {
  GitBranch,
  Search,
  Plus,
  CheckCircle,
  Clock,
  XCircle,
  AlertCircle,
  ArrowRight,
  FileSearch,
  ArrowUpRight,
} from "lucide-react";
import { cn, formatDate, formatNumber } from "../lib/utils";
import {
  useSignalHubStore,
  useFilteredSignals,
  type IntegratedSignal,
} from "../stores/signalHub";

function SignalCard({ signal }: { signal: IntegratedSignal }) {
  const [isHovered, setIsHovered] = useState(false);
  const { selectSignal } = useSignalHubStore();

  const getStatusColor = (status: IntegratedSignal["status"]) => {
    switch (status) {
      case "ready":
        return "border-l-emerald-500";
      case "processing":
        return "border-l-blue-500";
      case "failed":
        return "border-l-red-500";
      default:
        return "border-l-slate-500";
    }
  };

  const getGovernanceIcon = (governance: IntegratedSignal["governance"]) => {
    switch (governance) {
      case "Approved":
        return <CheckCircle className="w-4 h-4 text-emerald-400" />;
      case "Pending":
        return <Clock className="w-4 h-4 text-amber-400" />;
      case "Rejected":
        return <XCircle className="w-4 h-4 text-red-400" />;
    }
  };

  const getGovernanceColor = (governance: IntegratedSignal["governance"]) => {
    switch (governance) {
      case "Approved":
        return "bg-emerald-500/10 text-emerald-400";
      case "Pending":
        return "bg-amber-500/10 text-amber-400";
      case "Rejected":
        return "bg-red-500/10 text-red-400";
    }
  };

  const getSharpeColor = (value?: number) => {
    if (value === undefined) return "text-slate-500";
    if (value >= 1.5) return "text-emerald-400";
    if (value >= 1.0) return "text-blue-400";
    if (value >= 0.5) return "text-amber-400";
    return "text-red-400";
  };

  return (
    <div
      className={cn(
        "relative bg-slate-900/50 border border-slate-800 rounded-lg p-4 transition-all duration-200 border-l-4",
        getStatusColor(signal.status),
        isHovered && "bg-slate-800/50 border-slate-700"
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-semibold text-white">{signal.name}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{signal.datasetUrn}</p>
        </div>
        <span
          className={cn(
            "px-2 py-0.5 rounded text-xs font-medium",
            getGovernanceColor(signal.governance)
          )}
        >
          {signal.governance}
        </span>
      </div>

      {/* Status */}
      {signal.status === "processing" ? (
        <div className="mb-3">
          <div className="flex items-center gap-2 text-blue-400">
            <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm">{signal.progressStep || "Processing..."}</span>
          </div>
        </div>
      ) : (
        /* Sharpe Ratio Flow */
        <div className="flex items-center gap-4 mb-3">
          <div className="flex-1">
            <span className="text-xs text-slate-500">Research IS</span>
            <div className={cn("text-lg font-mono", getSharpeColor(signal.researchSharpe))}>
              {signal.researchSharpe !== undefined
                ? formatNumber(signal.researchSharpe)
                : "—"}
            </div>
          </div>
          <ArrowRight className="w-4 h-4 text-slate-600" />
          <div className="flex-1">
            <span className="text-xs text-slate-500">Live IS</span>
            <div className={cn("text-lg font-mono", getSharpeColor(signal.liveSharpe))}>
              {signal.liveSharpe !== undefined
                ? formatNumber(signal.liveSharpe)
                : "—"}
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-slate-500">
          {getGovernanceIcon(signal.governance)}
          <span>Created {formatDate(signal.createdAt)}</span>
        </div>

        {/* Action Buttons (visible on hover) */}
        <div
          className={cn(
            "flex items-center gap-2 transition-opacity duration-200",
            isHovered ? "opacity-100" : "opacity-0"
          )}
        >
          <button
            onClick={() => selectSignal(signal.id)}
            className="flex items-center gap-1 px-2 py-1 text-slate-400 hover:text-white hover:bg-slate-700 rounded transition-colors"
          >
            <FileSearch className="w-3.5 h-3.5" />
            <span>Audit</span>
          </button>
          {signal.governance === "Pending" && signal.status === "ready" && (
            <button className="flex items-center gap-1 px-2 py-1 text-indigo-400 hover:text-white hover:bg-indigo-600 rounded transition-colors">
              <ArrowUpRight className="w-3.5 h-3.5" />
              <span>Promote</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function SignalHubPage() {
  const { searchTerm, statusFilter, setSearchTerm, setStatusFilter, setIsIntegrateModalOpen } =
    useSignalHubStore();
  const filteredSignals = useFilteredSignals();

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="flex-shrink-0 px-6 py-4 border-b border-slate-800">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <GitBranch className="w-6 h-6 text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">Signal Hub</h1>
            <p className="text-sm text-slate-400">
              Bridge Research artifacts to Trading execution. Manage lineage, governance, and deployment.
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mt-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search signals..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="all">All Status</option>
            <option value="approved">Approved</option>
            <option value="pending">Pending</option>
            <option value="rejected">Rejected</option>
          </select>

          <button
            onClick={() => setIsIntegrateModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Integrate Signal</span>
          </button>
        </div>
      </header>

      {/* Signal Grid */}
      <main className="flex-1 overflow-y-auto p-6">
        {filteredSignals.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-500">
            <AlertCircle className="w-12 h-12 mb-4" />
            <p>No signals found</p>
            <p className="text-sm mt-1">Try adjusting your filters or integrate a new signal</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {filteredSignals.map((signal) => (
              <SignalCard key={signal.id} signal={signal} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
