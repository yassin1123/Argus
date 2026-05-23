"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  CommentThread,
  FirmMemberLite,
  getOverview,
  OverviewGroup,
  OverviewResponse,
  resolveSection,
} from "@/lib/api/comments";

import { useComments } from "./CommentsController";

interface Props {
  sessionId: string;
  /** Current user — drives the "my mentions" filter shortcut. */
  currentUserId: string;
  /** Firm members for author-filter dropdown rendering. */
  firmMembers: FirmMemberLite[];
  /** Hide for non-members per W16/D3 hard rule (read-only viewers
   *  still see threads, but no compose/resolve UI in the panel — the
   *  overview is read-side; the controller's panel handles writes). */
  canResolveSections: boolean;
  /** Optional banner ("Engagement is approved — comments allowed but
   *  edits won't auto-revert"). */
  lockedBanner?: string | null;
}

type ResolvedFilter = "all" | "unresolved" | "resolved";

/**
 * Engagement-level comment overview — W16/D4.
 *
 * Lists every thread on the engagement, grouped by anchor
 * (section → claim → artifact → text_range → engagement). Each row is
 * clickable: it opens the :class:`ThreadPanel` scoped to that anchor
 * via :func:`useComments`.
 *
 * Filters: resolved/unresolved, by author, and "mentioning me" (which
 * is the same shape as W16/D4's ``MyMentions`` view but scoped to one
 * engagement). The host page decides where to mount the component;
 * the workspace shell drops it in a side panel or modal.
 */
export default function CommentOverview({
  sessionId,
  currentUserId,
  firmMembers,
  canResolveSections,
  lockedBanner = null,
}: Props) {
  const { openThread } = useComments();
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [resolvedFilter, setResolvedFilter] = useState<ResolvedFilter>("unresolved");
  const [authorId, setAuthorId] = useState<string>("");
  const [mentioningMe, setMentioningMe] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolvedSections, setResolvedSections] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const opts: Parameters<typeof getOverview>[1] = {};
      if (resolvedFilter !== "all") {
        opts.resolved = resolvedFilter === "resolved";
      }
      if (authorId) opts.author_id = authorId;
      if (mentioningMe) opts.mentioning = currentUserId;
      const next = await getOverview(sessionId, opts);
      setData(next);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId, resolvedFilter, authorId, mentioningMe, currentUserId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const memberById = useMemo(() => {
    const m = new Map<string, FirmMemberLite>();
    for (const fm of firmMembers) m.set(fm.user_id, fm);
    return m;
  }, [firmMembers]);

  const handleResolveSection = async (sectionPath: string) => {
    if (!canResolveSections) return;
    if (
      !confirm(
        `Resolve every unresolved thread on "${sectionPath}"? Each is logged individually.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await resolveSection(sessionId, sectionPath);
      setResolvedSections((p) => [...p, `${sectionPath} (${res.resolved_count})`]);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="comment-overview"
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
          Discussion
        </h2>
        <span
          data-testid="overview-unresolved-count"
          style={{ fontSize: 13, color: "#6b7280" }}
        >
          {data ? `${data.unresolved_total} unresolved · ${data.total} total` : "Loading…"}
        </span>
      </header>

      {lockedBanner && (
        <div
          data-testid="overview-locked-banner"
          style={{
            padding: "8px 10px",
            background: "#fff8e1",
            border: "1px solid #fde68a",
            borderRadius: 6,
            fontSize: 12,
            color: "#92400e",
          }}
        >
          {lockedBanner}
        </div>
      )}

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          fontSize: 12,
          alignItems: "center",
        }}
      >
        <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
          Status:
          <select
            data-testid="overview-resolved-filter"
            value={resolvedFilter}
            onChange={(e) => setResolvedFilter(e.target.value as ResolvedFilter)}
            style={{ padding: "2px 6px", fontSize: 12 }}
          >
            <option value="all">All</option>
            <option value="unresolved">Unresolved</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>

        <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
          Author:
          <select
            data-testid="overview-author-filter"
            value={authorId}
            onChange={(e) => setAuthorId(e.target.value)}
            style={{ padding: "2px 6px", fontSize: 12 }}
          >
            <option value="">Anyone</option>
            {firmMembers.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name || m.email || m.user_id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input
            type="checkbox"
            data-testid="overview-mentioning-me"
            checked={mentioningMe}
            onChange={(e) => setMentioningMe(e.target.checked)}
          />
          Mentioning me
        </label>
      </div>

      {error && (
        <div
          data-testid="overview-error"
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

      {resolvedSections.length > 0 && (
        <div
          data-testid="overview-bulk-resolve-toast"
          style={{
            padding: "6px 10px",
            background: "#dcfce7",
            border: "1px solid #86efac",
            borderRadius: 6,
            color: "#166534",
            fontSize: 12,
          }}
        >
          Resolved: {resolvedSections.join(", ")}
        </div>
      )}

      {data === null && (
        <div style={{ color: "#6b7280", fontSize: 13 }}>Loading…</div>
      )}
      {data !== null && data.groups.length === 0 && (
        <div
          data-testid="overview-empty"
          style={{ color: "#6b7280", fontSize: 13 }}
        >
          No threads match the current filters.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {data?.groups.map((g) => (
          <OverviewGroupView
            key={g.key}
            group={g}
            memberById={memberById}
            canResolveSections={canResolveSections}
            busy={busy}
            onResolveSection={handleResolveSection}
            onOpenThread={(thread) => {
              openThread({
                anchor_type: thread.root.anchor_type,
                anchor_ref: thread.root.anchor_ref,
                label: g.label,
              });
            }}
          />
        ))}
      </div>
    </section>
  );
}

interface GroupViewProps {
  group: OverviewGroup;
  memberById: Map<string, FirmMemberLite>;
  canResolveSections: boolean;
  busy: boolean;
  onResolveSection: (sectionPath: string) => void;
  onOpenThread: (thread: CommentThread) => void;
}

function OverviewGroupView({
  group,
  memberById,
  canResolveSections,
  busy,
  onResolveSection,
  onOpenThread,
}: GroupViewProps) {
  const isSection = group.anchor_type === "section";
  const sectionPath =
    isSection && group.anchor_ref?.section_path
      ? group.anchor_ref.section_path
      : null;
  const showBulkResolve =
    canResolveSections && sectionPath && group.unresolved > 0;

  return (
    <article
      data-testid={`overview-group-${group.key}`}
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        padding: 10,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <strong data-testid={`overview-group-label-${group.key}`}>
            {group.label}
          </strong>
          <span style={{ fontSize: 11, color: "#6b7280" }}>
            {group.unresolved} unresolved · {group.total} total
          </span>
        </div>
        {showBulkResolve && (
          <button
            type="button"
            onClick={() => onResolveSection(sectionPath!)}
            disabled={busy}
            data-testid={`overview-bulk-resolve-${sectionPath}`}
            style={{
              padding: "2px 8px",
              background: "#dcfce7",
              border: "1px solid #86efac",
              borderRadius: 6,
              fontSize: 11,
              color: "#166534",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            Resolve all
          </button>
        )}
      </header>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {group.threads.map((t) => {
          const author = memberById.get(t.root.author_id);
          const authorLabel = author?.full_name || author?.email || t.root.author_id.slice(0, 8);
          return (
            <li key={t.root.id}>
              <button
                type="button"
                onClick={() => onOpenThread(t)}
                data-testid={`overview-thread-${t.root.id}`}
                style={{
                  width: "100%",
                  textAlign: "left",
                  background: t.resolved ? "#f9fafb" : "white",
                  border: "1px solid #e5e7eb",
                  borderRadius: 4,
                  padding: "6px 8px",
                  fontSize: 12,
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                <span style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                  <span style={{ fontWeight: 500, color: "#111827" }}>{authorLabel}</span>
                  {t.resolved && (
                    <span
                      style={{
                        fontSize: 10,
                        background: "#fef9c3",
                        color: "#854d0e",
                        padding: "0 4px",
                        borderRadius: 3,
                      }}
                    >
                      resolved
                    </span>
                  )}
                  {t.orphaned && (
                    <span
                      style={{
                        fontSize: 10,
                        background: "#fff7ed",
                        color: "#9a3412",
                        padding: "0 4px",
                        borderRadius: 3,
                      }}
                    >
                      orphaned
                    </span>
                  )}
                </span>
                <span style={{ color: "#4b5563", whiteSpace: "pre-wrap" }}>
                  {t.root.body.length > 140
                    ? `${t.root.body.slice(0, 140)}…`
                    : t.root.body}
                </span>
                {t.replies.length > 0 && (
                  <span style={{ fontSize: 11, color: "#6b7280" }}>
                    {t.replies.length} {t.replies.length === 1 ? "reply" : "replies"}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </article>
  );
}
