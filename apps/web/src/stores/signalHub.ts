import { create } from "zustand";

export interface IntegratedSignal {
  id: string;
  name: string;
  datasetUrn: string;
  transformer: string;
  status: "processing" | "ready" | "failed";
  progressStep?: string;
  createdAt: string;
  researchSharpe?: number;
  liveSharpe?: number;
  governance: "Pending" | "Approved" | "Rejected";
}

interface SignalHubState {
  signals: IntegratedSignal[];
  selectedSignalId: string | null;
  isLoading: boolean;
  searchTerm: string;
  statusFilter: string;
  isIntegrateModalOpen: boolean;

  // Actions
  setSignals: (signals: IntegratedSignal[]) => void;
  addSignal: (signal: IntegratedSignal) => void;
  updateSignal: (id: string, updates: Partial<IntegratedSignal>) => void;
  selectSignal: (id: string | null) => void;
  setSearchTerm: (term: string) => void;
  setStatusFilter: (status: string) => void;
  setIsIntegrateModalOpen: (open: boolean) => void;
  setIsLoading: (loading: boolean) => void;
}

// Sample demo data
const demoSignals: IntegratedSignal[] = [
  {
    id: "sig-1",
    name: "Momentum Alpha",
    datasetUrn: "optaic://datasets/equity-prices",
    transformer: "MomentumTransformer",
    status: "ready",
    createdAt: new Date(Date.now() - 86400000 * 3).toISOString(),
    researchSharpe: 1.45,
    liveSharpe: 1.32,
    governance: "Approved",
  },
  {
    id: "sig-2",
    name: "Mean Reversion Beta",
    datasetUrn: "optaic://datasets/equity-prices",
    transformer: "MeanReversionTransformer",
    status: "ready",
    createdAt: new Date(Date.now() - 86400000 * 7).toISOString(),
    researchSharpe: 0.98,
    liveSharpe: 0.87,
    governance: "Pending",
  },
  {
    id: "sig-3",
    name: "Volatility Signal",
    datasetUrn: "optaic://datasets/options-vol",
    transformer: "VolatilityTransformer",
    status: "processing",
    progressStep: "Computing features...",
    createdAt: new Date().toISOString(),
    governance: "Pending",
  },
  {
    id: "sig-4",
    name: "Sentiment Overlay",
    datasetUrn: "optaic://datasets/news-sentiment",
    transformer: "SentimentTransformer",
    status: "ready",
    createdAt: new Date(Date.now() - 86400000 * 14).toISOString(),
    researchSharpe: 0.72,
    liveSharpe: undefined,
    governance: "Rejected",
  },
];

export const useSignalHubStore = create<SignalHubState>((set) => ({
  signals: demoSignals,
  selectedSignalId: null,
  isLoading: false,
  searchTerm: "",
  statusFilter: "all",
  isIntegrateModalOpen: false,

  setSignals: (signals) => set({ signals }),

  addSignal: (signal) =>
    set((state) => ({ signals: [signal, ...state.signals] })),

  updateSignal: (id, updates) =>
    set((state) => ({
      signals: state.signals.map((s) =>
        s.id === id ? { ...s, ...updates } : s
      ),
    })),

  selectSignal: (id) => set({ selectedSignalId: id }),

  setSearchTerm: (term) => set({ searchTerm: term }),

  setStatusFilter: (status) => set({ statusFilter: status }),

  setIsIntegrateModalOpen: (open) => set({ isIntegrateModalOpen: open }),

  setIsLoading: (loading) => set({ isLoading: loading }),
}));

// Selector for filtered signals
export const useFilteredSignals = () => {
  const { signals, searchTerm, statusFilter } = useSignalHubStore();

  return signals.filter((signal) => {
    const matchesSearch = signal.name
      .toLowerCase()
      .includes(searchTerm.toLowerCase());
    const matchesStatus =
      statusFilter === "all" ||
      signal.governance.toLowerCase() === statusFilter.toLowerCase();
    return matchesSearch && matchesStatus;
  });
};
