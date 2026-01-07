import { useEffect, useMemo, useState } from "react";

import type { MergeRequestOut, PromotionRequestOut } from "@sdk";
import { useApiClient } from "@/services/api";
import { useSessionStore } from "@/state/session";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface ApprovalItem {
  kind: "merge" | "promotion";
  id: string;
  title: string;
  status: string;
  detail: MergeRequestOut | PromotionRequestOut;
}

export const ApprovalsPanel = ({ resourceId }: { resourceId?: string | null }) => {
  const api = useApiClient();
  const { tenantId, principalId } = useSessionStore();
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchApprovals = async () => {
    if (!api || !resourceId || !tenantId || !principalId) return;
    setLoading(true);
    try {
      const page = await api.resources.listChildren(resourceId, { limit: 50 });
      const mergeIds = page.items.filter((item) => item.type === "MergeRequest");
      const promoIds = page.items.filter((item) => item.type === "PromotionRequest");

      const mergeRequests = await Promise.all(
        mergeIds.map((item) => api.mergeRequests.get(item.id)),
      );
      const promotions = await Promise.all(
        promoIds.map((item) => api.promotions.get(item.id)),
      );

      const next: ApprovalItem[] = [
        ...mergeRequests.map((mr) => ({
          kind: "merge" as const,
          id: mr.id,
          title: mr.title || `MR ${mr.id.slice(0, 6)}`,
          status: mr.status,
          detail: mr,
        })),
        ...promotions.map((pr) => ({
          kind: "promotion" as const,
          id: pr.id,
          title: `Promotion ${pr.id.slice(0, 6)}`,
          status: pr.status,
          detail: pr,
        })),
      ].filter((item) => ["open", "approved"].includes(item.status));
      setItems(next);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchApprovals();
  }, [resourceId]);

  const canAct = useMemo(() => !loading && api && tenantId && principalId, [
    api,
    loading,
    tenantId,
    principalId,
  ]);

  const handleApproval = async (item: ApprovalItem, decision: "approve" | "reject") => {
    if (!api || !tenantId || !principalId) return;
    if (item.kind === "merge") {
      await api.mergeRequests.approve(item.id, { decision });
    } else {
      await api.promotions.approve(item.id, { decision });
    }
    await fetchApprovals();
  };

  const handleExecute = async (item: ApprovalItem) => {
    if (!api) return;
    if (item.kind === "merge") {
      await api.mergeRequests.merge(item.id);
    } else {
      await api.promotions.execute(item.id);
    }
    await fetchApprovals();
  };

  if (!resourceId) {
    return (
      <div className="rounded-2xl border border-dashed border-fog-200 bg-white p-6 text-sm text-ink-700">
        Select a resource to view approvals.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-ink-900">Approvals</h3>
          <p className="text-sm text-ink-700">
            Merge requests and promotions scoped to the selected resource.
          </p>
        </div>
        <Button variant="secondary" onClick={fetchApprovals} disabled={loading}>
          Refresh
        </Button>
      </div>
      {items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-fog-200 bg-white p-6 text-sm text-ink-700">
          No approvals found in this scope.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={`${item.kind}-${item.id}`}>
                <TableCell className="font-medium">
                  {item.kind === "merge" ? "Merge Request" : "Promotion"}
                </TableCell>
                <TableCell>{item.title}</TableCell>
                <TableCell className="capitalize">{item.status}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!canAct}
                      onClick={() => handleApproval(item, "approve")}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!canAct}
                      onClick={() => handleApproval(item, "reject")}
                    >
                      Reject
                    </Button>
                    <Button
                      size="sm"
                      disabled={!canAct || item.status !== "approved"}
                      onClick={() => handleExecute(item)}
                    >
                      Execute
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
};
