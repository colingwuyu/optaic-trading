import type { ActivityEventV1 } from "@sdk";
import type { ComponentType } from "react";
import { Bell, CheckCircle2, Clock3, MessageSquare, Tag } from "lucide-react";

import { cn } from "@/lib/utils";
import { useActivityStore } from "@/state/activities";

const iconMap: Record<string, ComponentType<{ className?: string }>> = {
  "message.": MessageSquare,
  "merge.": Tag,
  "promote.": Tag,
  "resource.": CheckCircle2,
  "channel.": MessageSquare,
};

const getIcon = (action: string) => {
  const prefix = Object.keys(iconMap).find((key) => action.startsWith(key));
  return prefix ? iconMap[prefix] : Bell;
};

const formatTime = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  });

const ActivityItem = ({ event }: { event: ActivityEventV1 }) => {
  const Icon = getIcon(event.action);
  const title = event.ui_hints?.title || event.action;
  const summary =
    event.ui_hints?.summary ||
    (Object.keys(event.payload || {}).length
      ? JSON.stringify(event.payload)
      : "No payload");

  return (
    <div className="flex gap-4 rounded-2xl border border-fog-200 bg-white p-4 shadow-sm">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-fog-100">
        <Icon className="h-5 w-5 text-ink-800" />
      </div>
      <div className="flex-1 space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-ink-900">{title}</div>
            <div className="text-xs text-ink-700/70">{event.action}</div>
          </div>
          <div className="flex items-center gap-2 text-xs text-ink-700/70">
            <Clock3 className="h-3.5 w-3.5" />
            {formatTime(event.created_at)}
          </div>
        </div>
        <p className="text-sm text-ink-800/90">{summary}</p>
        <div className="flex flex-wrap gap-2 text-xs text-ink-700">
          <span className="rounded-full bg-fog-100 px-2 py-1">
            Actor: {event.actor.display_name || event.actor.principal_id}
          </span>
          <span className="rounded-full bg-fog-100 px-2 py-1">
            Resource: {event.resource.resource_type}
          </span>
          {event.targets?.user_inbox && (
            <span className="rounded-full bg-fog-100 px-2 py-1">
              Inbox event
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export const ActivityTimeline = ({
  principalId,
  resourceId,
}: {
  principalId: string;
  resourceId?: string | null;
}) => {
  const { events, inboxIds, resourceIds } = useActivityStore();
  const resourceEvents = resourceId ? resourceIds[resourceId] ?? [] : [];

  const combined = Array.from(new Set([...inboxIds, ...resourceEvents]))
    .map((id) => events[id])
    .filter(Boolean)
    .sort(
      (a, b) => {
        const timeDiff =
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        if (timeDiff !== 0) return timeDiff;
        return b.event_id.localeCompare(a.event_id);
      },
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm text-ink-700">
        <span className="nav-pill">Inbox: {principalId}</span>
        {resourceId && (
          <span className={cn("nav-pill bg-white/60")}>
            Resource: {resourceId}
          </span>
        )}
      </div>
      {combined.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-fog-200 bg-white p-6 text-sm text-ink-700">
          No activity yet. Create or update resources to see events here.
        </div>
      ) : (
        <div className="space-y-4">
          {combined.map((event) => (
            <ActivityItem key={event.event_id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
};
