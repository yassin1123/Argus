"use client";

import { useCallback, useEffect, useState } from "react";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

interface AuditEvent {
  id: number;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

interface Props {
  sessionId: string;
  /** Cap the number of events the feed loads — defaults to 100. */
  limit?: number;
  /** When supplied, used to resolve actor_user_id → display name. */
  memberLookup?: Map<string, { name?: string; email?: string }>;
}

const COLLAB_PREFIXES = [
  "engagement.member_",
  "engagement.lead_changed",
  "section.",
  "review.",
  "comment.",
  "task.",
];

const ACTION_LABEL: Record<string, string> = {
  "engagement.member_assigned":   "added to engagement",
  "engagement.member_role_changed": "role changed",
  "engagement.member_removed":    "removed from engagement",
  "engagement.lead_changed":      "became engagement lead",
  "section.assigned":             "assigned section",
  "section.status_changed":       "changed section status",
  "section.needs_review":         "marked section as needs review",
  "section.unassigned":           "unassigned section",
  "review.submitted":             "submitted for review",
  "review.approved":              "approved engagement",
  "review.requested_changes":     "requested changes",
  "review.resolve_pointer":       "resolved a review pointer",
  "review.reopened":              "reopened the engagement",
  "review.auto_revert":           "auto-reverted on edit",
  "review.delivered":             "marked engagement delivered",
  "comment.created":              "posted a comment",
  "comment.replied":              "replied to a thread",
  "comment.resolved":             "resolved a thread",
  "comment.unresolved":           "reopened a thread",
  "comment.edited":               "edited a comment",
  "comment.deleted":              "deleted a comment",
  "comment.mention":              "@-mentioned someone",
  "task.created":                 "created a task",
  "task.completed":               "completed a task",
};

const ACTION_ICON: Record<string, string> = {
  "engagement.": "👥",
  "section.":    "📝",
  "review.":     "✓",
  "comment.":    "💬",
  "task.":       "•",
};

function _icon(action: string): string {
  for (const [prefix, icon] of Object.entries(ACTION_ICON)) {
    if (action.startsWith(prefix)) return icon;
  }
  return "•";
}

function _label(action: string): string {
  return ACTION_LABEL[action] || action.replaceAll("_", " ").replaceAll(".", " ");
}

function _formatTimestamp(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * Lightweight per-engagement collaboration feed. Pulls from the
 * existing audit_events table (no new schema) filtered to the
 * collaboration-relevant action prefixes (engagement.* / section.*
 * / review.* / comment.* / task.*).
 *
 * Read-only — refresh on mount + manual refresh button. No
 * WebSocket / push per W17/D4 hard rule.
 */
export default function ActivityFeed({
  sessionId,
  limit = 100,
  memberLookup,
}: Props) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(
        `${BASE_URL}/api/admin/audit?engagement_id=${encodeURIComponent(sessionId)}&limit=${limit}`,
        { credentials: FETCH_CREDS, cache: "no-store" },
      );
      if (!r.ok) {
        throw new Error(`audit fetch ${r.status}`);
      }
      const body = (await r.json()) as { events: AuditEvent[] };
      const filtered = (body.events || []).filter((e) =>
        COLLAB_PREFIXES.some((p) => e.action.startsWith(p)),
      );
      setEvents(filtered);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [sessionId, limit]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section
      data-testid="activity-feed"
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Activity</h2>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={busy}
          data-testid="activity-feed-refresh"
          style={{
            background: "transparent",
            border: 0,
            padding: 0,
            color: "#6b7280",
            fontSize: 11,
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {error && (
        <div
          data-testid="activity-feed-error"
          style={{
            padding: "6px 8px",
            background: "#fee2e2",
            color: "#991b1b",
            border: "1px solid #fecaca",
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          {error}
        </div>
      )}

      {events === null && !error && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>Loading…</div>
      )}
      {events !== null && events.length === 0 && (
        <div data-testid="activity-feed-empty" style={{ fontSize: 12, color: "#6b7280" }}>
          No collaboration activity yet.
        </div>
      )}

      <ul style={{ listStyle: "none", margin: 0, padding: 0,
                    display: "flex", flexDirection: "column", gap: 4 }}>
        {events?.map((e) => {
          const actorInfo = e.actor_user_id ? memberLookup?.get(e.actor_user_id) : undefined;
          const actor = actorInfo?.name || actorInfo?.email || e.actor_email ||
                         (e.actor_user_id ? e.actor_user_id.slice(0, 8) : "system");
          return (
            <li
              key={e.id}
              data-testid={`activity-event-${e.id}`}
              data-action={e.action}
              style={{
                display: "flex",
                gap: 6,
                fontSize: 12,
                padding: "4px 6px",
                borderRadius: 4,
                background: "#fafafa",
                border: "1px solid #f3f4f6",
              }}
            >
              <span aria-hidden style={{ flexShrink: 0, width: 18, textAlign: "center" }}>
                {_icon(e.action)}
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <strong style={{ color: "#111827" }}>{actor}</strong>{" "}
                <span style={{ color: "#4b5563" }}>{_label(e.action)}</span>
                {_payloadHint(e.payload) && (
                  <span style={{ color: "#6b7280" }}>
                    {" · "}
                    {_payloadHint(e.payload)}
                  </span>
                )}
              </span>
              <span style={{ flexShrink: 0, fontSize: 10, color: "#9ca3af" }}>
                {_formatTimestamp(e.created_at)}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function _payloadHint(payload: Record<string, unknown>): string {
  if (!payload) return "";
  // Cheap hints: surface the most useful field per action type.
  const sp = payload.section_path;
  if (typeof sp === "string") return sp;
  const role = payload.role || payload.new_role;
  if (typeof role === "string") return role;
  const status = payload.new_status || payload.status;
  if (typeof status === "string") return String(status);
  return "";
}
