import { useMemo } from "react";
import { ApiClient } from "@sdk";
import { useSessionStore } from "@/state/session";

const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const useApiClient = () => {
  const { tenantId, principalId } = useSessionStore();

  return useMemo(() => {
    if (!tenantId || !principalId) return null;
    return new ApiClient(apiBaseUrl, {
      tenantId,
      principalId,
    });
  }, [tenantId, principalId]);
};

export { apiBaseUrl };
