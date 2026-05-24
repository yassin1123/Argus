"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getUnreadCount } from "@/lib/api/notifications";

const DEFAULT_POLL_MS = 30_000;

interface Props {
  href: string;
  label: string;
  active: boolean;
  children: React.ReactNode;
  pollIntervalMs?: number;
}

/**
 * LeftRail nav item that overlays a polled unread-count badge on
 * top of the bell icon. Same poll pattern as
 * :class:`NotificationBell` but rendered as a Next.js ``<Link>`` so
 * it slots into the existing LeftRail navigation chrome without
 * disturbing the click-to-route behaviour.
 *
 * Per W18/D4 hard rule "no WebSockets for v1": we poll every 30s.
 */
export default function NotificationNavItem({
  href,
  label,
  active,
  children,
  pollIntervalMs = DEFAULT_POLL_MS,
}: Props) {
  const [unread, setUnread] = useState<number | null>(null);
  const stopped = useRef(false);

  const tick = useCallback(async () => {
    try {
      const r = await getUnreadCount();
      if (stopped.current) return;
      setUnread(r.unread_count);
    } catch {
      // Silent — the bell shouldn't surface API errors in the nav.
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

  const badge = unread === null
    ? null
    : unread > 99
      ? "99+"
      : unread > 0
        ? String(unread)
        : null;

  return (
    <Link
      href={href}
      title={label}
      aria-label={badge ? `${label} (${unread} unread)` : label}
      aria-current={active ? "page" : undefined}
      data-testid="notification-nav-item"
      data-unread-count={unread ?? -1}
      className={`group relative flex h-10 w-10 items-center justify-center rounded-sm transition-colors ${
        active
          ? "bg-argus-primary text-argus-inverse"
          : "text-argus-secondary hover:bg-elevated hover:text-argus-primary"
      }`}
    >
      {children}
      {badge && (
        <span
          data-testid="notification-nav-badge"
          className="absolute -top-1 -right-1 inline-flex items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white"
          style={{ minWidth: 16, height: 16, lineHeight: 1 }}
        >
          {badge}
        </span>
      )}
      {active ? (
        <span
          aria-hidden
          className="absolute -left-3 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-argus-accent"
        />
      ) : null}
    </Link>
  );
}
