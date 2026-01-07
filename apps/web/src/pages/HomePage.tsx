import { useEffect, useMemo, useRef, useState } from "react";
import { LogOut, RefreshCw, Radio } from "lucide-react";

import { ActivityTimeline } from "@/components/ActivityTimeline";
import { ApprovalsPanel } from "@/components/ApprovalsPanel";
import { CatalogPanel } from "@/components/CatalogPanel";
import { ChatPanel } from "@/components/ChatPanel";
import { ResourceTree } from "@/components/ResourceTree";
import { SystemUpdatesPanel } from "@/components/SystemUpdatesPanel";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiClient } from "@/services/api";
import { createRealtimeClient } from "@/services/realtime";
import { useActivityStore } from "@/state/activities";
import { useResourceStore } from "@/state/resources";
import { useSessionStore } from "@/state/session";
import { useChatStore } from "@/state/chat";

export const HomePage = () => {
  const api = useApiClient();
  const { tenantId, principalId, rootResourceId, clearSession } = useSessionStore();
  const { tree, selectedId, setTree } = useResourceStore();
  const { addEvent, setInboxEvents, setResourceEvents } = useActivityStore();
  const { addChannelEvent } = useChatStore();
  const [connectionStatus, setConnectionStatus] = useState<
    "connected" | "connecting" | "disconnected"
  >("disconnected");
  const [loadingTree, setLoadingTree] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const realtimeRef = useRef<ReturnType<typeof createRealtimeClient> | null>(null);
  const hasConnectedRef = useRef(false);

  const resourceId = selectedId || rootResourceId || null;

  const refreshTree = async () => {
    if (!api || !rootResourceId) return;
    setLoadingTree(true);
    try {
      const treeData = await api.resources.getTree(rootResourceId, 3);
      setTree(treeData);
    } finally {
      setLoadingTree(false);
    }
  };

  useEffect(() => {
    if (rootResourceId) {
      void refreshTree();
    }
  }, [rootResourceId, api]);

  useEffect(() => {
    if (!api || !principalId) return;
    const loadInbox = async () => {
      const inbox = await api.activities.list({ limit: 50 });
      const targeted = inbox.items.filter((event) =>
        event.targets?.user_inbox?.includes(principalId),
      );
      setInboxEvents(targeted);
    };
    void loadInbox();
  }, [api, principalId]);

  useEffect(() => {
    if (!api || !resourceId) return;
    const loadResourceActivity = async () => {
      const resourceFeed = await api.activities.list({
        resourceId,
        limit: 50,
      });
      setResourceEvents(resourceId, resourceFeed.items);
    };
    void loadResourceActivity();
  }, [api, resourceId]);

  useEffect(() => {
    if (!api || !principalId || !tenantId) return;
    let cancelled = false;

    const catchUp = async () => {
      try {
        const activityState = useActivityStore.getState();
        const chatState = useChatStore.getState();
        const selectedResourceId =
          useResourceStore.getState().selectedId ||
          useSessionStore.getState().rootResourceId;

        if (activityState.lastInboxSeen) {
          const inbox = await api.activities.list({
            after: activityState.lastInboxSeen,
            limit: 200,
          });
          const targeted = inbox.items.filter((event) =>
            event.targets?.user_inbox?.includes(principalId),
          );
          if (targeted.length) {
            setInboxEvents(targeted);
          }
        }

        if (selectedResourceId) {
          const after = activityState.lastResourceSeen[selectedResourceId];
          if (after) {
            const resourceFeed = await api.activities.list({
              resourceId: selectedResourceId,
              after,
              limit: 200,
            });
            if (resourceFeed.items.length) {
              setResourceEvents(selectedResourceId, resourceFeed.items);
            }
          }
        }

        const activeChannelId = chatState.activeChannelId;
        if (activeChannelId) {
          const after = chatState.lastMessageSeen[activeChannelId];
          if (after) {
            const messages = await api.chat.listMessages(activeChannelId, {
              after,
              limit: 200,
            });
            if (messages.items.length) {
              chatState.setMessages(activeChannelId, messages.items);
            }
          }
        }
      } catch (err) {
        setBootstrapError(
          (err as Error).message || "Realtime catch-up failed",
        );
      }
    };

    const bootstrap = async () => {
      setBootstrapError(null);
      try {
        const data = await api.realtimeBootstrap();
        if (cancelled) return;
        const realtime = createRealtimeClient();
        realtimeRef.current = realtime;
        realtime.on("connecting", () => setConnectionStatus("connecting"));
        realtime.on("disconnected", () => setConnectionStatus("disconnected"));
        realtime.on("connected", () => {
          setConnectionStatus("connected");
          if (hasConnectedRef.current) {
            void catchUp();
          } else {
            hasConnectedRef.current = true;
          }
        });
        realtime.connect(data.connection_token);
        Object.entries(data.subscription_tokens).forEach(([channel, token]) => {
          realtime.subscribe(channel, token, (event) => {
            addEvent(event, principalId);
            event.targets?.chat_channels?.forEach((channelId) => {
              addChannelEvent(channelId, event);
            });
          });
        });
      } catch (err) {
        setBootstrapError((err as Error).message || "Realtime bootstrap failed");
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
      realtimeRef.current?.disconnect();
      realtimeRef.current = null;
      setConnectionStatus("disconnected");
      hasConnectedRef.current = false;
    };
  }, [api, principalId, tenantId, addEvent, addChannelEvent, setInboxEvents, setResourceEvents]);

  const greeting = useMemo(() => {
    if (!principalId) return "Welcome back";
    return `Welcome, ${principalId.slice(0, 8)}...`;
  }, [principalId]);

  return (
    <div className="flex min-h-screen">
      <aside className="w-80 border-r border-fog-200 bg-white/80 p-6">
        <div className="mb-6 space-y-2">
          <h2 className="font-display text-2xl text-ink-900">Workspace</h2>
          <p className="text-xs text-ink-700">{greeting}</p>
        </div>
        <div className="mb-4 flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={refreshTree}
            disabled={loadingTree}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button variant="ghost" size="sm" onClick={clearSession}>
            <LogOut className="mr-2 h-4 w-4" />
            Sign out
          </Button>
        </div>
        {tree ? (
          <ResourceTree tree={tree} />
        ) : (
          <div className="rounded-xl border border-dashed border-fog-200 bg-white p-4 text-sm text-ink-700">
            {rootResourceId
              ? "Loading resource tree..."
              : "No root resource configured. Add one in login."}
          </div>
        )}
      </aside>
      <main className="flex-1 p-10">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl text-ink-900">
              Activity Command Center
            </h1>
            <p className="text-sm text-ink-700">
              Real-time events, conversations, and approvals in one view.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm shadow-sm">
              <Radio
                className={`h-4 w-4 ${
                  connectionStatus === "connected"
                    ? "text-green-500"
                    : connectionStatus === "connecting"
                    ? "text-yellow-500"
                    : "text-red-500"
                }`}
              />
              {connectionStatus === "connected" && "Live"}
              {connectionStatus === "connecting" && "Reconnecting"}
              {connectionStatus === "disconnected" && "Offline"}
            </div>
            {bootstrapError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-600">
                {bootstrapError}
              </div>
            )}
          </div>
        </div>

        <Tabs defaultValue="activity">
          <TabsList>
            <TabsTrigger value="activity">Activity</TabsTrigger>
            <TabsTrigger value="chat">Chat</TabsTrigger>
            <TabsTrigger value="approvals">Approvals</TabsTrigger>
            <TabsTrigger value="catalog">Catalog</TabsTrigger>
            <TabsTrigger value="system">System</TabsTrigger>
          </TabsList>

          <TabsContent value="activity">
            <ActivityTimeline
              principalId={principalId || ""}
              resourceId={resourceId}
            />
          </TabsContent>
          <TabsContent value="chat">
            <ChatPanel resourceId={resourceId} />
          </TabsContent>
          <TabsContent value="approvals">
            <ApprovalsPanel resourceId={resourceId} />
          </TabsContent>
          <TabsContent value="catalog">
            <CatalogPanel />
          </TabsContent>
          <TabsContent value="system">
            <SystemUpdatesPanel />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
};
