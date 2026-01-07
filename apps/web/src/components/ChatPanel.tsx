import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChatContainer,
  Conversation,
  ConversationList,
  MainContainer,
  Message,
  MessageInput,
  MessageList,
  Sidebar,
} from "@chatscope/chat-ui-kit-react";

import type { MessageOut } from "@sdk";
import { useApiClient } from "@/services/api";
import { useChatStore } from "@/state/chat";
import { useSessionStore } from "@/state/session";

const toChatMessage = (
  message: MessageOut,
  principalId: string,
): { model: any } => ({
  model: {
    message: message.body || "",
    sentTime: new Date(message.created_at).toLocaleTimeString(),
    sender: message.sender_principal_id,
    direction: message.sender_principal_id === principalId ? "outgoing" : "incoming",
  },
});

export const ChatPanel = ({ resourceId }: { resourceId?: string | null }) => {
  const api = useApiClient();
  const { principalId } = useSessionStore();
  const {
    channels,
    activeChannelId,
    setChannels,
    setActiveChannel,
    messages,
    setMessages,
    lastChatEvent,
  } = useChatStore();
  const [pendingAttachment, setPendingAttachment] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const channelMessages = useMemo(
    () => (activeChannelId ? messages[activeChannelId] ?? [] : []),
    [activeChannelId, messages],
  );

  const loadChannels = async () => {
    if (!api || !resourceId) return;
    const page = await api.chat.listChannels(resourceId);
    const next = page.items.map((item) => ({ id: item.id, name: item.name }));
    if (next.length) {
      setChannels(next);
      return;
    }
    try {
      await api.chat.listMessages(resourceId, { limit: 1 });
      setChannels([{ id: resourceId, name: `Channel ${resourceId.slice(0, 6)}` }]);
    } catch {
      setChannels([]);
    }
  };

  const loadMessages = async (channelId: string) => {
    if (!api) return;
    const page = await api.chat.listMessages(channelId, { limit: 50 });
    setMessages(channelId, page.items);
  };

  useEffect(() => {
    if (!resourceId) return;
    void loadChannels();
  }, [api, resourceId]);

  useEffect(() => {
    if (activeChannelId) {
      void loadMessages(activeChannelId);
    }
  }, [activeChannelId]);

  useEffect(() => {
    if (!lastChatEvent || !activeChannelId) return;
    if (!lastChatEvent.action.startsWith("message.")) return;
    if (!lastChatEvent.targets?.chat_channels?.includes(activeChannelId)) return;
    void loadMessages(activeChannelId);
  }, [lastChatEvent, activeChannelId]);

  const handleSend = async (
    innerHtml: string,
    textContent: string,
    innerText: string,
  ) => {
    if (!api || !activeChannelId || !principalId) return;
    const body = (textContent || innerText || innerHtml || "").trim();
    if (!body) return;
    setSending(true);
    try {
      const message = await api.chat.sendMessage(activeChannelId, { body });
      if (pendingAttachment) {
        const initPayload = await api.chat.uploadInit({
          channel_id: activeChannelId,
          filename: pendingAttachment.name,
          content_type: pendingAttachment.type || "application/octet-stream",
          bytes: pendingAttachment.size,
        });

        await fetch(initPayload.presigned_put_url, {
          method: "PUT",
          body: pendingAttachment,
          headers: initPayload.headers || {},
        });

        await api.chat.finalizeAttachment({
          message_id: message.id,
          object_key: initPayload.object_key,
        });
        setPendingAttachment(null);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }
      await loadMessages(activeChannelId);
    } finally {
      setSending(false);
    }
  };

  if (!resourceId) {
    return (
      <div className="rounded-2xl border border-dashed border-fog-200 bg-white p-6 text-sm text-ink-700">
        Select a resource to load chat channels.
      </div>
    );
  }

  return (
    <div className="chat-panel glass-card h-[620px] overflow-hidden">
      <MainContainer responsive>
        <Sidebar position="left" scrollable>
          <ConversationList>
            {channels.map((channel) => (
              <Conversation
                key={channel.id}
                name={channel.name}
                active={channel.id === activeChannelId}
                onClick={() => setActiveChannel(channel.id)}
              />
            ))}
          </ConversationList>
        </Sidebar>
        <ChatContainer>
          <MessageList>
            {channelMessages.map((message) => (
              <Message
                key={message.id}
                {...toChatMessage(message, principalId || "")}
              />
            ))}
          </MessageList>
          <MessageInput
            placeholder={
              pendingAttachment
                ? `Attachment: ${pendingAttachment.name}`
                : "Write a message..."
            }
            disabled={sending || !activeChannelId}
            attachButton
            sendButton
            onAttachClick={() => fileInputRef.current?.click()}
            onSend={handleSend}
          />
        </ChatContainer>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(event) =>
            setPendingAttachment(event.target.files?.[0] || null)
          }
        />
      </MainContainer>
    </div>
  );
};
