import type { ResourceTree as ResourceTreeNode } from "@sdk";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { useResourceStore } from "@/state/resources";

interface TreeProps {
  tree: ResourceTreeNode;
}

const TreeItem = ({ node, depth }: { node: ResourceTreeNode; depth: number }) => {
  const { selectedId, selectResource } = useResourceStore();
  const isSelected = selectedId === node.resource.id;

  return (
    <div>
      <button
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition",
          isSelected ? "bg-ink-900 text-white" : "hover:bg-fog-100",
        )}
        style={{ marginLeft: depth * 12 }}
        onClick={() => selectResource(node.resource.id)}
      >
        <ChevronRight
          className={cn(
            "h-4 w-4 transition",
            node.children.length ? "opacity-100" : "opacity-30",
          )}
        />
        <div>
          <div className="font-medium">{node.resource.name}</div>
          <div className="text-xs text-ink-700/70">{node.resource.type}</div>
        </div>
      </button>
      {node.children.map((child) => (
        <TreeItem key={child.resource.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
};

export const ResourceTree = ({ tree }: TreeProps) => (
  <div className="space-y-1">
    <TreeItem node={tree} depth={0} />
  </div>
);
