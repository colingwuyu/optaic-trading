import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiClient } from "@sdk";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiBaseUrl } from "@/services/api";
import { useSessionStore } from "@/state/session";

export const LoginPage = () => {
  const navigate = useNavigate();
  const { setSession } = useSessionStore();
  const [tenantId, setTenantId] = useState("");
  const [principalId, setPrincipalId] = useState("");
  const [rootResourceId, setRootResourceId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = () => {
    if (!tenantId || !principalId) {
      setError("Tenant ID and Principal ID are required.");
      return;
    }
    setError(null);
    setSession({
      tenantId,
      principalId,
      rootResourceId: rootResourceId || null,
    });
    navigate("/app");
  };

  const createDemo = async () => {
    setLoading(true);
    setError(null);
    try {
      const newTenantId = crypto.randomUUID();
      const ownerId = crypto.randomUUID();
      const viewerId = crypto.randomUUID();
      const client = new ApiClient(apiBaseUrl, {
        tenantId: newTenantId,
        principalId: ownerId,
      });

      const tenant = await client.createTenant({ name: "Demo Workspace" });

      await client.createPrincipal({
        id: viewerId,
        display_name: "Viewer",
        email: "viewer@example.com",
      });

      if (!tenant.root_resource_id) {
        throw new Error("Tenant root resource not returned.");
      }

      const space = await client.createResource({
        type: "Space",
        parent_id: tenant.root_resource_id,
        name: "Product Space",
      });

      const subspace = await client.createResource({
        type: "Subspace",
        parent_id: space.id,
        name: "Planning Hub",
      });

      const project = await client.createResource({
        type: "Project",
        parent_id: subspace.id,
        name: "Roadmap",
      });

      await client.createChannel({
        parent_id: project.id,
        channel_kind: "group",
        name: "Project Chat",
      });

      setSession({
        tenantId: newTenantId,
        principalId: ownerId,
        rootResourceId: tenant.root_resource_id || null,
      });
      navigate("/app");
    } catch (err) {
      setError((err as Error).message || "Failed to create demo tenant.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="glass-card w-full max-w-2xl p-10">
        <div className="mb-8 space-y-2">
          <h1 className="font-display text-3xl text-ink-900">
            Resource Activity Platform
          </h1>
          <p className="text-sm text-ink-700">
            Enter your dev tenant and principal to access the workspace.
          </p>
        </div>
        <div className="grid gap-4">
          <Input
            placeholder="Tenant ID"
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
          />
          <Input
            placeholder="Principal ID"
            value={principalId}
            onChange={(event) => setPrincipalId(event.target.value)}
          />
          <Input
            placeholder="Root Resource ID (optional)"
            value={rootResourceId}
            onChange={(event) => setRootResourceId(event.target.value)}
          />
        </div>
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
        <div className="mt-6 flex flex-wrap gap-3">
          <Button onClick={handleSubmit}>Enter Workspace</Button>
          <Button variant="secondary" onClick={createDemo} disabled={loading}>
            {loading ? "Creating..." : "Create demo tenant/users"}
          </Button>
        </div>
      </div>
    </div>
  );
};
