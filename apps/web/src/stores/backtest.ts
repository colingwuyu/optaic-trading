import { create } from "zustand";

export interface BacktestRun {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  startedAt: string;
  completedAt?: string;
  config: Record<string, unknown>;
  results?: BacktestResults;
}

export interface BacktestResults {
  sharpeRatio: number;
  totalReturn: number;
  volatility: number;
  maxDrawdown: number;
  equityCurve: { date: string; value: number }[];
  trades: number;
  winRate: number;
}

export interface ModelVersion {
  id: string;
  modelId: string;
  recalibrationDate: string;
  calibrationWindowDays: number;
  signalCount: number;
  globalR2: number;
}

interface BacktestState {
  runs: BacktestRun[];
  selectedRunId: string | null;
  isConfigOpen: boolean;
  activeTab: "overview" | "models" | "replay";
  replayDate: string;
  modelVersions: ModelVersion[];
  isLoading: boolean;

  // Actions
  setRuns: (runs: BacktestRun[]) => void;
  addRun: (run: BacktestRun) => void;
  updateRun: (id: string, updates: Partial<BacktestRun>) => void;
  selectRun: (id: string | null) => void;
  setIsConfigOpen: (open: boolean) => void;
  setActiveTab: (tab: "overview" | "models" | "replay") => void;
  setReplayDate: (date: string) => void;
  setModelVersions: (versions: ModelVersion[]) => void;
  setIsLoading: (loading: boolean) => void;
}

// Generate demo equity curve data
function generateEquityCurve(days: number, totalReturn: number): { date: string; value: number }[] {
  const curve: { date: string; value: number }[] = [];
  let value = 100;
  const dailyReturn = Math.pow(1 + totalReturn, 1 / days) - 1;
  const now = new Date();

  for (let i = days; i >= 0; i--) {
    const date = new Date(now);
    date.setDate(date.getDate() - i);

    // Add some noise
    const noise = (Math.random() - 0.5) * 0.02;
    value = value * (1 + dailyReturn + noise);

    curve.push({
      date: date.toISOString().split("T")[0],
      value: value,
    });
  }
  return curve;
}

// Demo data
const demoRuns: BacktestRun[] = [
  {
    id: "bt-1",
    name: "Momentum Strategy v2.3",
    status: "completed",
    startedAt: new Date(Date.now() - 86400000 * 2).toISOString(),
    completedAt: new Date(Date.now() - 86400000 * 2 + 3600000).toISOString(),
    config: { strategy: "momentum", lookback: 20 },
    results: {
      sharpeRatio: 1.45,
      totalReturn: 0.156,
      volatility: 0.12,
      maxDrawdown: 0.085,
      equityCurve: generateEquityCurve(252, 0.156),
      trades: 342,
      winRate: 0.54,
    },
  },
  {
    id: "bt-2",
    name: "Mean Reversion Long/Short",
    status: "completed",
    startedAt: new Date(Date.now() - 86400000 * 5).toISOString(),
    completedAt: new Date(Date.now() - 86400000 * 5 + 7200000).toISOString(),
    config: { strategy: "mean_reversion", zscore_threshold: 2.0 },
    results: {
      sharpeRatio: 0.98,
      totalReturn: 0.089,
      volatility: 0.095,
      maxDrawdown: 0.062,
      equityCurve: generateEquityCurve(252, 0.089),
      trades: 567,
      winRate: 0.48,
    },
  },
  {
    id: "bt-3",
    name: "Volatility Targeting",
    status: "running",
    startedAt: new Date(Date.now() - 1800000).toISOString(),
    config: { strategy: "vol_target", target_vol: 0.1 },
  },
];

const demoModelVersions: ModelVersion[] = [
  {
    id: "mv-1",
    modelId: "model-001",
    recalibrationDate: new Date(Date.now() - 86400000 * 7).toISOString(),
    calibrationWindowDays: 252,
    signalCount: 15,
    globalR2: 0.72,
  },
  {
    id: "mv-2",
    modelId: "model-002",
    recalibrationDate: new Date(Date.now() - 86400000 * 14).toISOString(),
    calibrationWindowDays: 504,
    signalCount: 23,
    globalR2: 0.68,
  },
  {
    id: "mv-3",
    modelId: "model-003",
    recalibrationDate: new Date(Date.now() - 86400000 * 30).toISOString(),
    calibrationWindowDays: 126,
    signalCount: 8,
    globalR2: 0.81,
  },
];

export const useBacktestStore = create<BacktestState>((set) => ({
  runs: demoRuns,
  selectedRunId: demoRuns[0].id,
  isConfigOpen: false,
  activeTab: "overview",
  replayDate: new Date().toISOString().split("T")[0],
  modelVersions: demoModelVersions,
  isLoading: false,

  setRuns: (runs) => set({ runs }),

  addRun: (run) => set((state) => ({ runs: [run, ...state.runs] })),

  updateRun: (id, updates) =>
    set((state) => ({
      runs: state.runs.map((r) => (r.id === id ? { ...r, ...updates } : r)),
    })),

  selectRun: (id) => set({ selectedRunId: id }),

  setIsConfigOpen: (open) => set({ isConfigOpen: open }),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setReplayDate: (date) => set({ replayDate: date }),

  setModelVersions: (versions) => set({ modelVersions: versions }),

  setIsLoading: (loading) => set({ isLoading: loading }),
}));

// Selector for selected run
export const useSelectedRun = () => {
  const { runs, selectedRunId } = useBacktestStore();
  return runs.find((r) => r.id === selectedRunId) ?? null;
};
