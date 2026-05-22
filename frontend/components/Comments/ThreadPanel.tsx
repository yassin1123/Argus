"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  AnchorRef,
  AnchorType,
  CommentRow,
  CommentThread,
  createComment,
  deleteComment,
  editComment,
  FirmMemberLite,
  listThreads,
  replyToComment,
  resolveThread,
  unresolveThread,
} from "@/lib/api/comments";

import MentionInput from "./MentionInput";

export interface ThreadPanelAnchor {
  anchor_type: AnchorType;
  anchor_ref?: AnchorRef;
  /** Human-readable label for the panel header (e.g.
   *  "synergy_estimate" or "claim_kgr_1"). */
  label: string;
}

interface Props {
  sessionId: string;
  /** Which anchor the panel is currently scoped to. ``null`` ->
   *  panel hidden. Parent controls open/close so multiple
   *  affordances can drive the same panel. */
  anchor: ThreadPanelAnchor | null;
  /** Current user (used for author-only edit/delete gates). */
  currentUserId: string;
  /** Firm members for @-mention autocomplete. */
  firmMembers: FirmMemberLite[];
  /** True when commenting should be hidden (non-member). Comments
   *  remain *allowed* on approved/delivered engagements per W16/D3
   *  hard rule — only the composer is gated. */
  canComment: boolean;
  /** Optional banner the parent renders to tell the user the
   *  engagement is locked. We pass the message through verbatim. */
  lockedBanner?: string | null;
  onClose: () => void;
  /** Fires after every mutation so the parent can refresh badges. */
  onMutated?: () => void;
}

/**
 * Right-side slide-in thread panel.
 *
 * Scoped to a single anchor (engagement / section / claim / artifact /
 * text_range) at a time. Renders root + replies, lets the current user
 * compose a new root or reply, edit/delete their own comments, and
 * resolve/unresolve the thread. Orphan flag (text_range only) renders
 * inline as a warning row at the top of the thread.
 *
 * No real-time updates — refreshes happen on action. The W16/D3 hard
 * rule says polish is Phase 5; the layout here is the simplest panel
 * that satisfies every functional requirement.
 */
export default function ThreadPanel({
  sessionId,
  anchor,
  currentUserId,
  firmMembers,
  canComment,
  lockedBanner = null,
  onClose,
  onMutated,
}: Props) {
  const [threads, setThreads] = useState<CommentThread[] | null>(null);
  const [composeBody, setComposeBody] = useState("");
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const memberById = useMemo(() => {
    const m = new Map<string, FirmMemberLite>();
    for (const fm of firmMembers) m.set(fm.user_id, fm);
    return m;
  }, [firmMembers]);

  const refresh = useCallback(async () => {
    if (!anchor) return;
    try {
      const res = await listThreads(sessionId);
      // Filter client-side to the panel's anchor — the API supports
      // anchor_type filtering but not per-ref. The list endpoint is
      // cheap enough that client filtering is fine for a single
      // engagement's comment volume.
      const matches = res.threads.filter((t) =>
        anchorMatches(t.root, anchor),
      );
      setThreads(matches);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId, anchor]);

  useEffect(() => {
    if (!anchor) {
      setThreads(null);
      return;
    }
    setError(null);
    void refresh();
  }, [anchor, refresh]);

  if (!anchor) return null;

  const handleCompose = async () => {
    if (!composeBody.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createComment(sessionId, {
        anchor_type: anchor.anchor_type,
        anchor_ref: anchor.anchor_ref,
        body: composeBody.trim(),
      });
      setComposeBody("");
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleReply = async (rootId: string) => {
    const draft = replyDrafts[rootId]?.trim();
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      await replyToComment(rootId, draft);
      setReplyDrafts((p) => ({ ...p, [rootId]: "" }));
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleResolveToggle = async (root: CommentRow) => {
    setBusy(true);
    setError(null);
    try {
      if (root.resolved) {
        await unresolveThread(root.id);
      } else {
        await resolveThread(root.id);
      }
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleEditSubmit = async (commentId: string) => {
    if (!editDraft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await editComment(commentId, editDraft.trim());
      setEditingId(null);
      setEditDraft("");
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (commentId: string) => {
    if (!confirm("Delete this comment? It will be hidden but retained for audit.")) return;
    setBusy(true);
    setError(null);
    try {
      await deleteComment(commentId);
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside
      data-testid="thread-panel"
      role="complementary"
      aria-label={`Comments — ${anchor.label}`}
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        bottom: 0,
        width: 400,
        background: "white",
        borderLeft: "1px solid #e5e7eb",
        boxShadow: "-4px 0 14px rgba(0,0,0,0.04)",
        display: "flex",
        flexDirection: "column",
        zIndex: 40,
      }}
    >
      <header
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div>
          <div style={{ fontSize: 13, color: "#6b7280" }}>Comments on</div>
          <div data-testid="thread-anchor-label" style={{ fontWeight: 600 }}>
            {anchor.label}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          data-testid="thread-panel-close"
          aria-label="Close thread panel"
          style={{
            background: "transparent",
            border: 0,
            fontSize: 22,
            lineHeight: 1,
            cursor: "pointer",
            color: "#6b7280",
          }}
        >
          ×
        </button>
      </header>

      {lockedBanner && (
        <div
          data-testid="thread-locked-banner"
          style={{
            padding: "10px 16px",
            background: "#fff8e1",
            borderBottom: "1px solid #fde68a",
            fontSize: 13,
            color: "#92400e",
          }}
        >
          {lockedBanner}
        </div>
      )}

      {error && (
        <div
          data-testid="thread-error"
          style={{
            padding: "10px 16px",
            background: "#fee2e2",
            color: "#991b1b",
            fontSize: 13,
            borderBottom: "1px solid #fecaca",
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {threads === null && (
          <div style={{ color: "#6b7280", fontSize: 13 }}>Loading…</div>
        )}
        {threads !== null && threads.length === 0 && (
          <div
            data-testid="thread-empty"
            style={{ color: "#6b7280", fontSize: 13 }}
          >
            No comments yet on this {anchor.anchor_type}.
          </div>
        )}
        {threads?.map((t) => (
          <ThreadView
            key={t.root.id}
            thread={t}
            currentUserId={currentUserId}
            memberById={memberById}
            firmMembers={firmMembers}
            replyDraft={replyDrafts[t.root.id] ?? ""}
            onReplyDraftChange={(v) =>
              setReplyDrafts((p) => ({ ...p, [t.root.id]: v }))
            }
            onReply={() => handleReply(t.root.id)}
            onResolveToggle={() => handleResolveToggle(t.root)}
            editingId={editingId}
            editDraft={editDraft}
            onEditStart={(id, body) => {
              setEditingId(id);
              setEditDraft(body);
            }}
            onEditDraftChange={setEditDraft}
            onEditSubmit={handleEditSubmit}
            onEditCancel={() => {
              setEditingId(null);
              setEditDraft("");
            }}
            onDelete={handleDelete}
            busy={busy}
            canComment={canComment}
          />
        ))}
      </div>

      {canComment && (
        <footer
          style={{
            padding: "12px 16px",
            borderTop: "1px solid #e5e7eb",
            background: "#f9fafb",
          }}
        >
          <MentionInput
            value={composeBody}
            onChange={setComposeBody}
            members={firmMembers}
            placeholder={`New comment on ${anchor.label}…`}
            rows={3}
            disabled={busy}
            onSubmit={handleCompose}
            testId="thread-compose-input"
          />
          <div
            style={{
              marginTop: 8,
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <button
              type="button"
              onClick={handleCompose}
              disabled={busy || !composeBody.trim()}
              data-testid="thread-compose-submit"
              style={{
                padding: "6px 12px",
                background: composeBody.trim() ? "#111827" : "#9ca3af",
                color: "white",
                border: 0,
                borderRadius: 6,
                cursor: composeBody.trim() ? "pointer" : "not-allowed",
                fontSize: 13,
              }}
            >
              Comment
            </button>
          </div>
        </footer>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ThreadViewProps {
  thread: CommentThread;
  currentUserId: string;
  memberById: Map<string, FirmMemberLite>;
  firmMembers: FirmMemberLite[];
  replyDraft: string;
  onReplyDraftChange: (v: string) => void;
  onReply: () => void;
  onResolveToggle: () => void;
  editingId: string | null;
  editDraft: string;
  onEditStart: (id: string, body: string) => void;
  onEditDraftChange: (v: string) => void;
  onEditSubmit: (id: string) => void;
  onEditCancel: () => void;
  onDelete: (id: string) => void;
  busy: boolean;
  canComment: boolean;
}

function ThreadView({
  thread,
  currentUserId,
  memberById,
  firmMembers,
  replyDraft,
  onReplyDraftChange,
  onReply,
  onResolveToggle,
  editingId,
  editDraft,
  onEditStart,
  onEditDraftChange,
  onEditSubmit,
  onEditCancel,
  onDelete,
  busy,
  canComment,
}: ThreadViewProps) {
  const { root, replies, resolved, orphaned } = thread;

  return (
    <section
      data-testid={`thread-${root.id}`}
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 12,
        background: resolved ? "#f9fafb" : "white",
      }}
    >
      {orphaned && (
        <div
          data-testid={`thread-orphan-flag-${root.id}`}
          style={{
            padding: "6px 8px",
            background: "#fff7ed",
            border: "1px solid #fed7aa",
            borderRadius: 6,
            color: "#9a3412",
            fontSize: 12,
            marginBottom: 10,
          }}
        >
          <div style={{ fontWeight: 600 }}>
            The text this refers to has changed
          </div>
          {root.anchor_ref?.quoted_text && (
            <div style={{ marginTop: 4, fontStyle: "italic" }}>
              “{root.anchor_ref.quoted_text}”
            </div>
          )}
        </div>
      )}

      <CommentView
        comment={root}
        currentUserId={currentUserId}
        memberById={memberById}
        firmMembers={firmMembers}
        isEditing={editingId === root.id}
        editDraft={editDraft}
        onEditStart={() => onEditStart(root.id, root.body)}
        onEditDraftChange={onEditDraftChange}
        onEditSubmit={() => onEditSubmit(root.id)}
        onEditCancel={onEditCancel}
        onDelete={() => onDelete(root.id)}
      />

      {replies.length > 0 && (
        <div
          style={{
            marginTop: 8,
            paddingLeft: 12,
            borderLeft: "2px solid #e5e7eb",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {replies.map((r) => (
            <CommentView
              key={r.id}
              comment={r}
              currentUserId={currentUserId}
              memberById={memberById}
              firmMembers={firmMembers}
              isEditing={editingId === r.id}
              editDraft={editDraft}
              onEditStart={() => onEditStart(r.id, r.body)}
              onEditDraftChange={onEditDraftChange}
              onEditSubmit={() => onEditSubmit(r.id)}
              onEditCancel={onEditCancel}
              onDelete={() => onDelete(r.id)}
            />
          ))}
        </div>
      )}

      <div
        style={{
          marginTop: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <button
          type="button"
          onClick={onResolveToggle}
          disabled={busy}
          data-testid={`thread-resolve-toggle-${root.id}`}
          style={{
            padding: "4px 10px",
            background: resolved ? "#fef9c3" : "#dcfce7",
            border: `1px solid ${resolved ? "#facc15" : "#86efac"}`,
            borderRadius: 6,
            fontSize: 12,
            cursor: busy ? "not-allowed" : "pointer",
            color: resolved ? "#854d0e" : "#166534",
          }}
        >
          {resolved ? "Reopen" : "Resolve"}
        </button>
      </div>

      {canComment && (
        <div style={{ marginTop: 10 }}>
          <MentionInput
            value={replyDraft}
            onChange={onReplyDraftChange}
            members={firmMembers}
            placeholder="Reply…"
            rows={2}
            disabled={busy}
            onSubmit={onReply}
            testId={`thread-reply-input-${root.id}`}
          />
          <div
            style={{
              marginTop: 6,
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <button
              type="button"
              onClick={onReply}
              disabled={busy || !replyDraft.trim()}
              data-testid={`thread-reply-submit-${root.id}`}
              style={{
                padding: "4px 10px",
                background: replyDraft.trim() ? "#111827" : "#9ca3af",
                color: "white",
                border: 0,
                borderRadius: 6,
                fontSize: 12,
                cursor: replyDraft.trim() ? "pointer" : "not-allowed",
              }}
            >
              Reply
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

interface CommentViewProps {
  comment: CommentRow;
  currentUserId: string;
  memberById: Map<string, FirmMemberLite>;
  firmMembers: FirmMemberLite[];
  isEditing: boolean;
  editDraft: string;
  onEditStart: () => void;
  onEditDraftChange: (v: string) => void;
  onEditSubmit: () => void;
  onEditCancel: () => void;
  onDelete: () => void;
}

function CommentView({
  comment,
  currentUserId,
  memberById,
  firmMembers,
  isEditing,
  editDraft,
  onEditStart,
  onEditDraftChange,
  onEditSubmit,
  onEditCancel,
  onDelete,
}: CommentViewProps) {
  const author = memberById.get(comment.author_id);
  const isMine = comment.author_id === currentUserId;
  const authorLabel = author?.full_name || author?.email || comment.author_id.slice(0, 8);
  const created = formatTimestamp(comment.created_at);
  const edited = comment.edited_at ? formatTimestamp(comment.edited_at) : null;

  return (
    <div data-testid={`comment-${comment.id}`}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 12,
          color: "#6b7280",
        }}
      >
        <span style={{ fontWeight: 600, color: "#111827" }}>{authorLabel}</span>
        <span>{created}</span>
        {edited && <span data-testid={`comment-edited-${comment.id}`}>edited</span>}
      </div>
      {isEditing ? (
        <div style={{ marginTop: 6 }}>
          <MentionInput
            value={editDraft}
            onChange={onEditDraftChange}
            members={firmMembers}
            rows={2}
            onSubmit={onEditSubmit}
            testId={`comment-edit-input-${comment.id}`}
          />
          <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
            <button
              type="button"
              onClick={onEditSubmit}
              disabled={!editDraft.trim()}
              data-testid={`comment-edit-save-${comment.id}`}
              style={{
                padding: "4px 10px",
                background: editDraft.trim() ? "#111827" : "#9ca3af",
                color: "white",
                border: 0,
                borderRadius: 6,
                fontSize: 12,
                cursor: editDraft.trim() ? "pointer" : "not-allowed",
              }}
            >
              Save
            </button>
            <button
              type="button"
              onClick={onEditCancel}
              data-testid={`comment-edit-cancel-${comment.id}`}
              style={{
                padding: "4px 10px",
                background: "white",
                color: "#374151",
                border: "1px solid #d1d5db",
                borderRadius: 6,
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div
          style={{
            marginTop: 4,
            whiteSpace: "pre-wrap",
            fontSize: 14,
            color: "#111827",
          }}
        >
          {renderBodyWithMentions(comment.body, memberById)}
        </div>
      )}
      {isMine && !isEditing && (
        <div
          style={{
            marginTop: 4,
            display: "flex",
            gap: 8,
            fontSize: 12,
          }}
        >
          <button
            type="button"
            onClick={onEditStart}
            data-testid={`comment-edit-${comment.id}`}
            style={{
              background: "transparent",
              border: 0,
              padding: 0,
              color: "#2563eb",
              cursor: "pointer",
            }}
          >
            Edit
          </button>
          <button
            type="button"
            onClick={onDelete}
            data-testid={`comment-delete-${comment.id}`}
            style={{
              background: "transparent",
              border: 0,
              padding: 0,
              color: "#dc2626",
              cursor: "pointer",
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function anchorMatches(root: CommentRow, anchor: ThreadPanelAnchor): boolean {
  if (root.anchor_type !== anchor.anchor_type) return false;
  if (!anchor.anchor_ref) return true;
  const ref = root.anchor_ref || {};
  for (const [k, v] of Object.entries(anchor.anchor_ref)) {
    if ((ref as Record<string, unknown>)[k] !== v) return false;
  }
  return true;
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

/**
 * Highlight @slug tokens in the rendered body. Tokens that resolve to a
 * firm member become a chip; unresolved tokens render as plain text.
 * The displayed slug is intentionally the same one the backend parser
 * matches (see ``buildSlugIndex`` in lib/api/comments.ts).
 */
function renderBodyWithMentions(
  body: string,
  memberById: Map<string, FirmMemberLite>,
) {
  // Build a reverse map slug -> member so we can render chips for
  // unambiguous matches. We rebuild here rather than threading the
  // slug index in because the body's mentions may include
  // collision-suffixed slugs the parent didn't precompute.
  const slugToUser = new Map<string, FirmMemberLite>();
  const byEmail: FirmMemberLite[] = Array.from(memberById.values());
  // Sort by user_id so reconstruction is deterministic with the
  // server's collision-suffix rule (server orders by created_at, but
  // user_id is the stable tiebreaker most often actually used here).
  byEmail.sort((a, b) => a.user_id.localeCompare(b.user_id));
  const counts = new Map<string, number>();
  for (const m of byEmail) {
    const local = (m.email || "").split("@", 1)[0].toLowerCase();
    const base = local.replace(/[^a-z0-9]+/g, ".").replace(/^\.+|\.+$/g, "");
    if (!base) continue;
    const n = counts.get(base) ?? 0;
    counts.set(base, n + 1);
    const slug = n === 0 ? base : `${base}${n + 1}`;
    slugToUser.set(slug, m);
  }

  const re = /@([a-z0-9][a-z0-9._-]{0,63})/g;
  const out: Array<JSX.Element | string> = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let idx = 0;
  while ((m = re.exec(body)) !== null) {
    if (m.index > last) out.push(body.slice(last, m.index));
    const slug = m[1];
    const user = slugToUser.get(slug);
    if (user) {
      out.push(
        <span
          key={`mention-${idx++}-${slug}`}
          data-testid={`mention-chip-${slug}`}
          style={{
            display: "inline-block",
            padding: "0 6px",
            margin: "0 2px",
            background: "#eef3ff",
            color: "#1d4ed8",
            borderRadius: 4,
            fontWeight: 500,
          }}
        >
          @{slug}
        </span>,
      );
    } else {
      out.push(m[0]);
    }
    last = m.index + m[0].length;
  }
  if (last < body.length) out.push(body.slice(last));
  return out;
}
