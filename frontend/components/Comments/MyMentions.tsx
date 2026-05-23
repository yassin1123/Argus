"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  CommentRow,
  FirmMemberLite,
  listMyMentions,
  MentionsResponse,
} from "@/lib/api/comments";

interface Props {
  /** The user whose mentions to display. Defaults to the current
   *  user; admins can pass any user_id in their firm. */
  userId: string;
  /** Optional unread cutoff — comments newer than this ISO timestamp
   *  are flagged as "new" in the list. Until W18 adds a real
   *  last-read pointer per user, callers can pass localStorage's
   *  last-visit timestamp here. */
  unreadSince?: string | null;
  /** Optional click handler. When the host integrates with router
   *  navigation it can route to ``/sessions/{session_id}`` and
   *  scroll to the anchor. */
  onSelect?: (mention: CommentRow) => void;
  /** Optional member list so we can resolve author user_ids to
   *  readable names; passed in by callers that already have it. */
  firmMembers?: FirmMemberLite[];
}

/**
 * "My mentions" view — W16/D4.
 *
 * Cross-engagement list of every live thread the user is @-mentioned
 * in. The :func:`listMyMentions` API enforces self-or-firm-admin so
 * the user_id prop is safe to take from props (the backend rejects
 * anything else).
 *
 * Layout: newest first. The "Unresolved only" toggle is a client
 * filter on top of the server response (also supported via API
 * query but kept simple for the UI). Rows are clickable when the
 * host provides ``onSelect``.
 */
export default function MyMentions({
  userId,
  unreadSince = null,
  onSelect,
  firmMembers,
}: Props) {
  const [data, setData] = useState<MentionsResponse | null>(null);
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const res = await listMyMentions(userId, {
        unresolved_only: unresolvedOnly,
      });
      setData(res);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [userId, unresolvedOnly]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const memberById = useMemo(() => {
    const m = new Map<string, FirmMemberLite>();
    for (const fm of firmMembers || []) m.set(fm.user_id, fm);
    return m;
  }, [firmMembers]);

  return (
    <section
      data-testid="my-mentions"
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <header style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>
          My mentions
        </h2>
        <span
          data-testid="my-mentions-total"
          style={{ fontSize: 13, color: "#6b7280" }}
        >
          {data ? `${data.total} total` : "Loading…"}
        </span>
      </header>

      <label style={{ display: "flex", gap: 6, fontSize: 12, alignItems: "center" }}>
        <input
          type="checkbox"
          data-testid="my-mentions-unresolved-only"
          checked={unresolvedOnly}
          onChange={(e) => setUnresolvedOnly(e.target.checked)}
        />
        Unresolved threads only
      </label>

      {error && (
        <div
          data-testid="my-mentions-error"
          style={{
            padding: "8px 10px",
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

      {data === null && (
        <div style={{ color: "#6b7280", fontSize: 13 }}>Loading…</div>
      )}
      {data !== null && data.mentions.length === 0 && (
        <div
          data-testid="my-mentions-empty"
          style={{ color: "#6b7280", fontSize: 13 }}
        >
          No mentions yet.
        </div>
      )}

      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {data?.mentions.map((m) => {
          const isUnread =
            unreadSince !== null && unreadSince !== undefined && m.created_at > unreadSince;
          const author = memberById.get(m.author_id);
          const authorLabel = author?.full_name || author?.email || m.author_id.slice(0, 8);
          return (
            <li key={m.id}>
              <button
                type="button"
                onClick={() => onSelect?.(m)}
                data-testid={`my-mention-${m.id}`}
                data-unread={isUnread ? "true" : "false"}
                style={{
                  width: "100%",
                  textAlign: "left",
                  background: isUnread ? "#eef3ff" : "white",
                  border: `1px solid ${isUnread ? "#bfdbfe" : "#e5e7eb"}`,
                  borderRadius: 6,
                  padding: "8px 10px",
                  fontSize: 12,
                  cursor: onSelect ? "pointer" : "default",
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                <span style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                  <span style={{ fontWeight: 500, color: "#111827" }}>{authorLabel}</span>
                  <span style={{ fontSize: 10, color: "#6b7280" }}>
                    {formatTimestamp(m.created_at)}
                  </span>
                  {isUnread && (
                    <span
                      style={{
                        fontSize: 10,
                        background: "#1d4ed8",
                        color: "white",
                        padding: "0 4px",
                        borderRadius: 3,
                      }}
                    >
                      new
                    </span>
                  )}
                </span>
                <span style={{ color: "#4b5563", whiteSpace: "pre-wrap" }}>
                  {m.body.length > 200 ? `${m.body.slice(0, 200)}…` : m.body}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
