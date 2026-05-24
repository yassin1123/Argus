"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  NOTIFICATION_TYPE_ICON,
  NotificationRow,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api/notifications";

import { notificationDeepLink } from "./deepLink";

interface Props {
  /** When true, render only unread items. Default false (show all). */
  unreadOnly?: boolean;
  /** Optional close handler — host renders the feed in a dropdown
   *  / overlay and wants the row click to dismiss it. */
  onClose?: () => void;
  /** Optional router override for tests (uses Next's router by
   *  default). */
  onNavigate?: (href: string) => void;
}

/**
 * Notification feed — newest-first list, click-to-navigate, mark-
 * read on click + "mark all read" action.
 *
 * Per W18/D4 hard rules:
 *   - Recipients only see their own notifications (the API enforces
 *     it; this component just fetches /api/me/notifications).
 *   - Clicking a notification always marks it read before navigating
 *     — no "navigate-without-read" path.
 *   - Grouping: recency only for v1; smarter buckets are Phase 5.
 *   - No WebSocket — the parent (NotificationBell) polls the
 *     unread-count; this feed re-fetches on open + after "mark all
 *     read".
 */
export default function NotificationFeed({
  unreadOnly = false,
  onClose,
  onNavigate,
}: Props) {
  const [rows, setRows] = useState<NotificationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const r = await listNotifications({ unread: unreadOnly, limit: 50 });
      setRows(r.notifications);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [unreadOnly]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleClick = async (n: NotificationRow) => {
    setBusy(true);
    try {
      // Mark read BEFORE navigating so the badge clears even when
      // the destination page replaces the route (and unmounts us
      // before the response lands).
      if (!n.read) {
        try {
          await markNotificationRead(n.id);
        } catch (e) {
          // Non-fatal — navigate anyway; the next refresh will
          // pick up the read state if the mark eventually succeeds.
          // eslint-disable-next-line no-console
          console.warn("markRead failed", e);
        }
      }
      const link = notificationDeepLink(n);
      if (onNavigate) {
        onNavigate(link.href);
      } else {
        router.push(link.href);
      }
      onClose?.();
    } finally {
      setBusy(false);
    }
  };

  const handleMarkAll = async () => {
    setBusy(true);
    setError(null);
    try {
      await markAllNotificationsRead();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="notification-feed"
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        boxShadow: "0 8px 24px rgba(0,0,0,0.08)",
        display: "flex",
        flexDirection: "column",
        width: 360,
        maxHeight: 480,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          padding: "10px 12px",
          borderBottom: "1px solid #e5e7eb",
        }}
      >
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>
          Notifications
        </h3>
        <button
          type="button"
          onClick={handleMarkAll}
          disabled={busy || (rows ?? []).every((r) => r.read)}
          data-testid="notification-feed-mark-all"
          style={{
            background: "transparent",
            border: 0,
            padding: 0,
            color: "#2563eb",
            fontSize: 11,
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          Mark all read
        </button>
      </header>

      {error && (
        <div
          data-testid="notification-feed-error"
          style={{
            padding: "8px 12px",
            background: "#fee2e2",
            color: "#991b1b",
            border: "1px solid #fecaca",
            fontSize: 12,
          }}
        >
          {error}
        </div>
      )}

      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          overflowY: "auto",
          flex: 1,
        }}
      >
        {rows === null && (
          <li style={{ padding: 12, color: "#6b7280", fontSize: 12 }}>
            Loading…
          </li>
        )}
        {rows !== null && rows.length === 0 && (
          <li
            data-testid="notification-feed-empty"
            style={{ padding: 12, color: "#6b7280", fontSize: 12 }}
          >
            No notifications.
          </li>
        )}
        {rows?.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              onClick={() => void handleClick(n)}
              data-testid={`notification-row-${n.id}`}
              data-read={n.read ? "true" : "false"}
              disabled={busy}
              style={{
                width: "100%",
                background: n.read ? "white" : "#eef3ff",
                border: 0,
                borderBottom: "1px solid #f3f4f6",
                padding: "10px 12px",
                textAlign: "left",
                cursor: busy ? "not-allowed" : "pointer",
                display: "flex",
                gap: 8,
                alignItems: "flex-start",
              }}
            >
              <span
                aria-hidden
                style={{
                  flexShrink: 0,
                  width: 20,
                  textAlign: "center",
                  fontSize: 14,
                }}
              >
                {NOTIFICATION_TYPE_ICON[n.notification_type] ?? "•"}
              </span>
              <span
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  fontSize: 12,
                  color: "#111827",
                }}
              >
                <span
                  data-testid={`notification-summary-${n.id}`}
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontWeight: n.read ? 400 : 600,
                  }}
                >
                  {n.summary}
                </span>
                <span style={{ fontSize: 10, color: "#6b7280" }}>
                  {_formatTimestamp(n.created_at)}
                </span>
              </span>
              {!n.read && (
                <span
                  aria-hidden
                  data-testid={`notification-unread-dot-${n.id}`}
                  style={{
                    flexShrink: 0,
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: "#2563eb",
                    marginTop: 6,
                  }}
                />
              )}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function _formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}
