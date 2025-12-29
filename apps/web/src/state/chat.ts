import { create } from "zustand";
import type { ActivityEventV1, MessageOut } from "@sdk";

export interface ChatChannel {
  id: string;
  name: string;
}

const compareMessages = (a: MessageOut, b: MessageOut) => {
  const timeDiff =
    new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  if (timeDiff !== 0) return timeDiff;
  return a.id.localeCompare(b.id);
};

const mergeMessages = (current: MessageOut[], incoming: MessageOut[]) => {
  const map = new Map(current.map((msg) => [msg.id, msg]));
  incoming.forEach((msg) => map.set(msg.id, msg));
  return Array.from(map.values()).sort(compareMessages);
};

const compareEvents = (a: ActivityEventV1, b: ActivityEventV1) => {
  const timeDiff =
    new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  if (timeDiff !== 0) return timeDiff;
  return a.event_id.localeCompare(b.event_id);
};

interface ChatState {
  channels: ChatChannel[];
  activeChannelId: string | null;
  messages: Record<string, MessageOut[]>;
  channelEvents: Record<string, ActivityEventV1[]>;
  lastChatEvent?: ActivityEventV1;
  lastMessageSeen: Record<string, string>;
  setChannels: (channels: ChatChannel[]) => void;
  setActiveChannel: (channelId: string) => void;
  setMessages: (channelId: string, messages: MessageOut[]) => void;
  appendMessage: (channelId: string, message: MessageOut) => void;
  addChannelEvent: (channelId: string, event: ActivityEventV1) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  channels: [],
  activeChannelId: null,
  messages: {},
  channelEvents: {},
  lastChatEvent: undefined,
  lastMessageSeen: {},
  setChannels: (channels) =>
    set({
      channels,
      activeChannelId: channels[0]?.id ?? null,
    }),
  setActiveChannel: (channelId) => set({ activeChannelId: channelId }),
  setMessages: (channelId, messages) => {
    const current = get().messages[channelId] ?? [];
    const nextMessages = mergeMessages(current, messages);
    const latest = nextMessages.at(-1)?.created_at;
    set({
      messages: { ...get().messages, [channelId]: nextMessages },
      lastMessageSeen: latest
        ? { ...get().lastMessageSeen, [channelId]: latest }
        : get().lastMessageSeen,
    });
  },
  appendMessage: (channelId, message) => {
    const current = get().messages[channelId] ?? [];
    const nextMessages = mergeMessages(current, [message]);
    const latest = nextMessages.at(-1)?.created_at;
    set({
      messages: {
        ...get().messages,
        [channelId]: nextMessages,
      },
      lastMessageSeen: latest
        ? { ...get().lastMessageSeen, [channelId]: latest }
        : get().lastMessageSeen,
    });
  },
  addChannelEvent: (channelId, event) => {
    const current = get().channelEvents[channelId] ?? [];
    if (current.find((item) => item.event_id === event.event_id)) return;
    set({
      channelEvents: {
        ...get().channelEvents,
        [channelId]: [...current, event].sort(compareEvents),
      },
      lastChatEvent: event,
    });
  },
}));
