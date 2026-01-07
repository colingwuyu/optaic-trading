/**
 * Notifications client for OptAIC TypeScript SDK
 */

import type {
  UUID,
  NotificationOut,
  NotificationPage,
  NotificationPreference,
} from "./types/index.js";

export interface INotificationsClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export class NotificationsClient {
  constructor(private client: INotificationsClient) {}

  /**
   * List notifications for the current user
   */
  async list(params?: {
    unreadOnly?: boolean;
    limit?: number;
    cursor?: string;
  }): Promise<NotificationPage> {
    const search = new URLSearchParams();
    if (params?.unreadOnly) search.set("unread_only", "true");
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.cursor) search.set("cursor", params.cursor);
    const query = search.toString();
    return this.client.request<NotificationPage>(
      `/notifications${query ? `?${query}` : ""}`
    );
  }

  /**
   * Mark a notification as read or unread
   */
  async markRead(
    notificationId: UUID,
    read = true
  ): Promise<NotificationOut> {
    return this.client.request<NotificationOut>(
      `/notifications/${notificationId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ read }),
      }
    );
  }

  /**
   * Mark all unread notifications as read
   */
  async markAllRead(): Promise<{ marked_count: number }> {
    return this.client.request<{ marked_count: number }>(
      "/notifications/mark-all-read",
      {
        method: "POST",
      }
    );
  }

  /**
   * Get unread notification count
   */
  async unreadCount(): Promise<{ unread_count: number }> {
    return this.client.request<{ unread_count: number }>(
      "/notifications/unread-count"
    );
  }

  /**
   * Get notification preferences
   */
  async getPreferences(): Promise<NotificationPreference> {
    return this.client.request<NotificationPreference>(
      "/notifications/preferences"
    );
  }

  /**
   * Update notification preferences
   */
  async updatePreferences(payload: {
    filterMode?: "all" | "mutations" | "custom";
    customActions?: string[];
    muted?: boolean;
  }): Promise<NotificationPreference> {
    const body: Record<string, unknown> = {};
    if (payload.filterMode !== undefined) body.filter_mode = payload.filterMode;
    if (payload.customActions !== undefined)
      body.custom_actions = payload.customActions;
    if (payload.muted !== undefined) body.muted = payload.muted;
    return this.client.request<NotificationPreference>(
      "/notifications/preferences",
      {
        method: "PUT",
        body: JSON.stringify(body),
      }
    );
  }
}
