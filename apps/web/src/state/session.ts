import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SessionState {
  tenantId: string | null;
  principalId: string | null;
  rootResourceId: string | null;
  setSession: (data: {
    tenantId: string;
    principalId: string;
    rootResourceId?: string | null;
  }) => void;
  clearSession: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      tenantId: null,
      principalId: null,
      rootResourceId: null,
      setSession: ({ tenantId, principalId, rootResourceId }) =>
        set({ tenantId, principalId, rootResourceId: rootResourceId ?? null }),
      clearSession: () => set({ tenantId: null, principalId: null, rootResourceId: null }),
    }),
    { name: "rap.session" },
  ),
);
