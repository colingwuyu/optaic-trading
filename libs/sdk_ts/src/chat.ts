/**
 * Chat client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  ChannelOut,
  ChannelCreate,
  MessageOut,
  MessagePage,
  MessageCreate,
  AttachmentUploadInitOut,
  AttachmentFinalizeOut,
} from "./types/index.js";

export interface IChatClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class ChatClient {
  constructor(private client: IChatClient) {}

  /**
   * Create a new chat channel
   */
  async createChannel(payload: ChannelCreate): Promise<ChannelOut> {
    return this.client.request<ChannelOut>("/chat/channels", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /**
   * List channels for a parent resource
   */
  async listChannels(
    parentId: string,
    params?: { limit?: number; cursor?: string }
  ): Promise<{ items: ChannelOut[]; next_cursor?: string | null }> {
    const search = new URLSearchParams();
    search.set("parent_id", parentId);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<{ items: ChannelOut[]; next_cursor?: string | null }>(
      `/chat/channels${query ? `?${query}` : ""}`
    );
  }

  /**
   * List messages in a channel
   */
  async listMessages(
    channelId: UUID,
    params?: { limit?: number; cursor?: string; after?: string }
  ): Promise<MessagePage> {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    if (params?.after) search.set("after", params.after);
    const query = search.toString();
    return this.client.request<MessagePage>(
      `/chat/channels/${channelId}/messages${query ? `?${query}` : ""}`
    );
  }

  /**
   * Send a message to a channel
   */
  async sendMessage(
    channelId: UUID,
    payload: MessageCreate
  ): Promise<MessageOut> {
    return this.client.request<MessageOut>(
      `/chat/channels/${channelId}/messages`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Edit a message
   */
  async editMessage(
    messageId: UUID,
    payload: MessageCreate
  ): Promise<MessageOut> {
    return this.client.request<MessageOut>(`/chat/messages/${messageId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  /**
   * Delete a message
   */
  async deleteMessage(messageId: UUID): Promise<MessageOut> {
    return this.client.request<MessageOut>(`/chat/messages/${messageId}`, {
      method: "DELETE",
    });
  }

  /**
   * Mark channel as read up to a message
   */
  async readChannel(
    channelId: UUID,
    lastReadMessageId: UUID
  ): Promise<{ success: boolean }> {
    return this.client.request<{ success: boolean }>(
      `/chat/channels/${channelId}/read`,
      {
        method: "POST",
        body: JSON.stringify({ last_read_message_id: lastReadMessageId }),
      }
    );
  }

  /**
   * Initialize attachment upload
   */
  async uploadInit(payload: {
    channel_id: UUID;
    filename: string;
    content_type: string;
    bytes: number;
    checksum?: string | null;
  }): Promise<AttachmentUploadInitOut> {
    return this.client.request<AttachmentUploadInitOut>(
      "/attachments/upload-init",
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  /**
   * Finalize attachment upload
   */
  async finalizeAttachment(payload: {
    message_id: UUID;
    object_key: string;
    checksum?: string | null;
  }): Promise<AttachmentFinalizeOut> {
    return this.client.request<AttachmentFinalizeOut>("/attachments/finalize", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
}
