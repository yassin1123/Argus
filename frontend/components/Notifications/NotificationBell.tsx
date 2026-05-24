"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getUnreadCount } from "@/lib/api/notifications";

const DEFAULT_POLL_MS = 30_000;

interface Props {
  /** Polled at this cadence. v1 uses 30s — fast enough that the
   *  partner sees "you've been mentioned" within half a minute,
   *  slow enough not to spam the API. Real-time push is Phase 5
   *  per W18/D4 hard rule. */
  pollIntervalMs?: number;
  /** Click handler — host opens the feed dropdown / overlay. */
  onClick?: () => void;
  /** Optional ARIA label override. */
  ariaLabel?: string;
}

/**
 * Bell icon + unread count badge. Polls
 * ``/api/me/notifications/unread-count`` on mount + every
 * ``pollIntervalMs`` (default 30s). Renders the count as a small
 * badge in the top-right corner of the icon; >99 collapses to "99+".
 *
 * Re-uses the LeftRail's bell SVG shape so the icon matches the
 * existing nav chrome (custom SVG, no icon library).
 */
export default function NotificationBell({
  pollIntervalMs = DEFAULT_POLL_MS,
  onClick,
  ariaLabel,
}: Props) {
  const [unread, setUnread] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stopped = useRef(false);

  const tick = useCallback(async () => {
    try {
      const r = await getUnreadCount();
      if (stopped.current) return;
      setUnread(r.unread_count);
      setError(null);
    } catch (e) {
      if (stopped.current) return;
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    stopped.current = false;
    void tick();
    const id = setInterval(tick, pollIntervalMs);
    return () => {
      stopped.current = true;
      clearInterval(id);
    };
  }, [tick, pollIntervalMs]);

  const label = ariaLabel
    ?? (unread && unread > 0 ? `${unread} unread notifications` : "Notifications");
  const badge = unread === null
    ? null
    : unread > 99
      ? "99+"
      : unread > 0
        ? String(unread)
        : null;

  return (
    <button
      type="button"
      onClick={onClick}
      data-testid="notification-bell"
      data-unread-count={unread ?? -1}
      aria-label={label}
      title={error ? `Bell error: ${error}` : label}
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 32,
        height: 32,
        background: "transparent",
        border: 0,
        padding: 0,
        cursor: "pointer",
        color: "inherit",
      }}
    >
      <svg
        width={18}
        height={18}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      {badge && (
        <span
          data-testid="notification-bell-badge"
          style={{
            position: "absolute",
            top: -2,
            right: -2,
            minWidth: 16,
            height: 16,
            padding: "0 4px",
            background: "#dc2626",
            color: "white",
            borderRadius: 8,
            fontSize: 10,
            fontWeight: 700,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            lineHeight: 1,
          }}
        >
          {badge}
        </span>
      )}
    </button>
  );
}
