// API client for /api/me/notifications + /api/me/notification-preferences
// — Phase 4 / Week 18 / Day 4. Backend at backend/api/notifications.py +
// backend/api/notification_preferences.py is the source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

// ---------------------------------------------------------------------------
// Types — mirror the backend dataclasses
// ---------------------------------------------------------------------------

export type NotificationType =
  | "mention"
  | "comment_reply"
  | "engagement_assigned"
  | "section_assigned"
  | "section_needs_review"
  | "task_assigned"
  | "review_requested"
  | "changes_requested"
  | "review_approved";

export type EmailStatus = "pending" | "sent" | "skipped" | "failed";

export interface NotificationRow {
  id: string;
  recipient_id: string;
  firm_id: string;
  notification_type: NotificationType;
  session_id: string | null;
  source_ref: Record<string, unknown>;
  actor_id: string | null;
  summary: string;
  read: boolean;
  read_at: string | null;
  created_at: string;
  email_status: EmailStatus;
}

export interface NotificationsResponse {
  user_id: string;
  notifications: NotificationRow[];
  count: number;
  next_before: string | null;
}

export interface UnreadCountResponse {
  user_id: string;
  unread_count: number;
}

export interface PreferenceEntry {
  notification_type: NotificationType;
  in_app: boolean;
  email: boolean;
  source?: "stored" | "default";
}

export interface PreferencesResponse {
  user_id: string;
  preferences: PreferenceEntry[];
  updated?: number;
  deleted?: number;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE_URL}${path}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
}

async function readJson(r: Response): Promise<unknown> {
  try {
    return await r.json();
  } catch {
    return await r.text();
  }
}

async function ensureOk(r: Response, label: string): Promise<void> {
  if (r.ok) return;
  const detail = await readJson(r);
  const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
  throw new Error(`${label} ${r.status}: ${msg}`);
}

// ---------------------------------------------------------------------------
// Inbox
// ---------------------------------------------------------------------------

export async function listNotifications(
  opts: { unread?: boolean; limit?: number; before?: string } = {},
): Promise<NotificationsResponse> {
  const qs = new URLSearchParams();
  if (opts.unread) qs.set("unread", "true");
  if (opts.limit) qs.set("limit", String(opts.limit));
  if (opts.before) qs.set("before", opts.before);
  const suffix = qs.toString();
  const r = await apiFetch(
    `/api/me/notifications${suffix ? `?${suffix}` : ""}`, { method: "GET" },
  );
  await ensureOk(r, "listNotifications");
  return (await r.json()) as NotificationsResponse;
}

export async function getUnreadCount(): Promise<UnreadCountResponse> {
  const r = await apiFetch(`/api/me/notifications/unread-count`, { method: "GET" });
  await ensureOk(r, "getUnreadCount");
  return (await r.json()) as UnreadCountResponse;
}

export async function markNotificationRead(
  notificationId: string,
): Promise<{ id: string; read: boolean; changed: boolean }> {
  const r = await apiFetch(
    `/api/notifications/${notificationId}/read`, { method: "POST" },
  );
  await ensureOk(r, "markNotificationRead");
  return (await r.json()) as { id: string; read: boolean; changed: boolean };
}

export async function markAllNotificationsRead(): Promise<{ marked_read: number }> {
  const r = await apiFetch(`/api/me/notifications/read-all`, { method: "POST" });
  await ensureOk(r, "markAllNotificationsRead");
  return (await r.json()) as { user_id: string; marked_read: number };
}

// ---------------------------------------------------------------------------
// Preferences (W18/D3 backend)
// ---------------------------------------------------------------------------

export async function getNotificationPreferences(): Promise<PreferencesResponse> {
  const r = await apiFetch(`/api/me/notification-preferences`, { method: "GET" });
  await ensureOk(r, "getNotificationPreferences");
  return (await r.json()) as PreferencesResponse;
}

export async function updateNotificationPreferences(
  preferences: Array<{ notification_type: string; in_app: boolean; email: boolean }>,
): Promise<PreferencesResponse> {
  const r = await apiFetch(`/api/me/notification-preferences`, {
    method: "PUT",
    body: JSON.stringify({ preferences }),
  });
  await ensureOk(r, "updateNotificationPreferences");
  return (await r.json()) as PreferencesResponse;
}

export async function resetNotificationPreferences(): Promise<PreferencesResponse> {
  const r = await apiFetch(`/api/me/notification-preferences/reset`, { method: "POST" });
  await ensureOk(r, "resetNotificationPreferences");
  return (await r.json()) as PreferencesResponse;
}

// ---------------------------------------------------------------------------
// Display labels
// ---------------------------------------------------------------------------

export const NOTIFICATION_TYPE_LABEL: Record<NotificationType, string> = {
  mention: "Mentions",
  comment_reply: "Comment replies",
  engagement_assigned: "Engagement assignments",
  section_assigned: "Section assignments",
  section_needs_review: "Section needs review",
  task_assigned: "Task assignments",
  review_requested: "Review requested",
  changes_requested: "Changes requested",
  review_approved: "Review approved",
};

export const NOTIFICATION_TYPE_ICON: Record<NotificationType, string> = {
  mention: "@",
  comment_reply: "💬",
  engagement_assigned: "👥",
  section_assigned: "📝",
  section_needs_review: "🔎",
  task_assigned: "•",
  review_requested: "✉",
  changes_requested: "⚠",
  review_approved: "✓",
};
