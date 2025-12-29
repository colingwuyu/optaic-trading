import { create } from "zustand";
import type { ResourceTree } from "@sdk";

interface ResourceState {
  tree: ResourceTree | null;
  selectedId: string | null;
  setTree: (tree: ResourceTree | null) => void;
  selectResource: (resourceId: string) => void;
}

export const useResourceStore = create<ResourceState>((set) => ({
  tree: null,
  selectedId: null,
  setTree: (tree) => set({ tree, selectedId: tree?.resource.id ?? null }),
  selectResource: (resourceId) => set({ selectedId: resourceId }),
}));
