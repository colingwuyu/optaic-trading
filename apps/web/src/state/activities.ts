import { create } from "zustand";
import type { ActivityEventV1 } from "@sdk";

const compareEvents = (a: ActivityEventV1, b: ActivityEventV1) => {
  const timeDiff =
    new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  if (timeDiff !== 0) return timeDiff;
  return a.event_id.localeCompare(b.event_id);
};

const maxTimestamp = (current: string | null | undefined, next: string) => {
  if (!current) return next;
  return new Date(next) > new Date(current) ? next : current;
};

const sortEventIds = (
  ids: string[],
  events: Record<string, ActivityEventV1>,
) =>
  ids
    .map((id) => events[id])
    .filter(Boolean)
    .sort(compareEvents)
    .map((event) => event.event_id);

interface ActivityState {
  events: Record<string, ActivityEventV1>;
  inboxIds: string[];
  resourceIds: Record<string, string[]>;
  lastEvent?: ActivityEventV1;
  lastInboxSeen?: string | null;
  lastResourceSeen: Record<string, string>;
  addEvent: (event: ActivityEventV1, principalId: string) => void;
  setInboxEvents: (events: ActivityEventV1[]) => void;
  setResourceEvents: (resourceId: string, events: ActivityEventV1[]) => void;
}

export const useActivityStore = create<ActivityState>((set, get) => ({
  events: {},
  inboxIds: [],
  resourceIds: {},
  lastEvent: undefined,
  lastInboxSeen: null,
  lastResourceSeen: {},
  addEvent: (event, principalId) => {
    const currentState = get();
    if (currentState.events[event.event_id]) return;

    const nextEvents = { ...currentState.events, [event.event_id]: event };
    let nextInboxIds = currentState.inboxIds;
    let nextInboxSeen = currentState.lastInboxSeen ?? null;
    const nextResourceIds = { ...currentState.resourceIds };
    const nextResourceSeen = { ...currentState.lastResourceSeen };

    if (event.targets?.user_inbox?.includes(principalId)) {
      nextInboxIds = sortEventIds(
        [...currentState.inboxIds, event.event_id],
        nextEvents,
      );
      nextInboxSeen = maxTimestamp(nextInboxSeen, event.created_at);
    }

    const resourceTargets = event.targets?.resource_channels ?? [];
    resourceTargets.forEach((resourceId) => {
      const current = nextResourceIds[resourceId] ?? [];
      nextResourceIds[resourceId] = sortEventIds(
        [...current, event.event_id],
        nextEvents,
      );
      nextResourceSeen[resourceId] = maxTimestamp(
        nextResourceSeen[resourceId],
        event.created_at,
      );
    });

    set({
      events: nextEvents,
      inboxIds: nextInboxIds,
      resourceIds: nextResourceIds,
      lastEvent: event,
      lastInboxSeen: nextInboxSeen,
      lastResourceSeen: nextResourceSeen,
    });
  },
  setInboxEvents: (events) => {
    const currentState = get();
    const nextEvents = { ...currentState.events };
    const incomingIds: string[] = [];
    let nextInboxSeen = currentState.lastInboxSeen ?? null;
    events.forEach((event) => {
      nextEvents[event.event_id] = event;
      incomingIds.push(event.event_id);
      nextInboxSeen = maxTimestamp(nextInboxSeen, event.created_at);
    });
    const inboxIds = sortEventIds(
      [...currentState.inboxIds, ...incomingIds],
      nextEvents,
    );
    set({ events: nextEvents, inboxIds, lastInboxSeen: nextInboxSeen });
  },
  setResourceEvents: (resourceId, events) => {
    const currentState = get();
    const nextEvents = { ...currentState.events };
    const incomingIds: string[] = [];
    let latest = currentState.lastResourceSeen[resourceId];
    events.forEach((event) => {
      nextEvents[event.event_id] = event;
      incomingIds.push(event.event_id);
      latest = maxTimestamp(latest, event.created_at);
    });
    const ids = sortEventIds(
      [...(currentState.resourceIds[resourceId] ?? []), ...incomingIds],
      nextEvents,
    );
    set({
      events: nextEvents,
      resourceIds: { ...currentState.resourceIds, [resourceId]: ids },
      lastResourceSeen: { ...currentState.lastResourceSeen, [resourceId]: latest },
    });
  },
}));
