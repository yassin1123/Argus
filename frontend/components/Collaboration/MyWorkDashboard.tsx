"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  EngagementBucket,
  MyWork,
  UnifiedTask,
  completeTask,
  createTask,
  getMyWork,
  getSessionWork,
} from "@/lib/api/collaboration";

interface Props {
  /** When undefined, fetches cross-engagement via /api/me/work.
   *  When supplied, fetches engagement-scoped via /api/sessions/{id}/work. */
  sessionId?: string;
  /** Required for the "create task" affordance. */
  currentUserId: string;
  /** Hide create-task UI for the engagement-scoped view of another
   *  user's work (lead/admin reading someone else's plate). */
  canCreate?: boolean;
  /** Optional click-through handler. Hosts route to
   *  /sessions/{session_id}#{section_path} or similar. */
  onOpenTask?: (task: UnifiedTask) => void;
  /** Compact mode for the engagement-scoped tab (drops the
   *  by-engagement grouping). */
  compact?: boolean;
}

const TYPE_ICON: Record<string, string> = {
  section_incomplete: "📝",
  change_request: "⚠️",
  mention: "@",
  comment_on_owned_section: "💬",
  explicit: "•",
};

const PRIORITY_TONE: Record<string, { bg: string; fg: string; border: string }> = {
  high:   { bg: "#fee2e2", fg: "#991b1b", border: "#fecaca" },
  medium: { bg: "#fef3c7", fg: "#92400e", border: "#fcd34d" },
  low:    { bg: "#f3f4f6", fg: "#4b5563", border: "#d1d5db" },
};

/**
 * Unified my-work dashboard — cross-engagement by default; pass
 * ``sessionId`` to scope. Surfaces derived tasks (mentions, change
 * requests, owned-section status) AND explicit ad-hoc tasks in one
 * priority-sorted list.
 *
 * Explicit tasks have a checkbox to complete; derived tasks deep-
 * link via ``onOpenTask``. The "create task" affordance at the
 * bottom is the lightweight escape hatch for ad-hoc to-dos.
 */
export default function MyWorkDashboard({
  sessionId,
  currentUserId,
  canCreate = true,
  onOpenTask,
  compact = false,
}: Props) {
  const [work, setWork] = useState<MyWork | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [creatingFor, setCreatingFor] = useState<string>("");

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const data = sessionId
        ? await getSessionWork(sessionId)
        : await getMyWork();
      setWork(data);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const buckets = useMemo<EngagementBucket[]>(() => {
    if (!work) return [];
    // Render order: highest "high" count first.
    return Object.values(work.by_engagement).sort(
      (a, b) =>
        b.counts.high - a.counts.high ||
        b.counts.medium - a.counts.medium ||
        b.engagement_title.localeCompare(a.engagement_title),
    );
  }, [work]);

  const handleComplete = async (taskId: string) => {
    setBusy(true);
    setError(null);
    try {
      await completeTask(taskId);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async () => {
    if (!newTitle.trim() || !creatingFor) return;
    setBusy(true);
    setError(null);
    try {
      await createTask(creatingFor, {
        title: newTitle.trim(),
        assigned_to: currentUserId,
      });
      setNewTitle("");
      setCreatingFor("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="my-work-dashboard"
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>My work</h2>
          {work && (
            <p
              data-testid="my-work-totals"
              style={{ margin: 0, fontSize: 11, color: "#6b7280" }}
            >
              {work.totals.high} high · {work.totals.medium} medium · {work.totals.low} low
            </p>
          )}
        </div>
      </header>

      {error && (
        <div
          data-testid="my-work-error"
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

      {work === null && (
        <div style={{ color: "#6b7280", fontSize: 12 }}>Loading…</div>
      )}
      {work && work.tasks.length === 0 && (
        <div data-testid="my-work-empty" style={{ color: "#6b7280", fontSize: 12 }}>
          Nothing on your plate. Nice.
        </div>
      )}

      {/* Grouped view */}
      {!compact && buckets.map((bucket) => (
        <EngagementBucketView
          key={bucket.session_id}
          bucket={bucket}
          busy={busy}
          onComplete={handleComplete}
          onOpenTask={onOpenTask}
        />
      ))}

      {/* Compact (engagement-scoped) — flat list */}
      {compact && work?.tasks.map((t) => (
        <TaskRow
          key={`${t.source}-${t.source_ref}`}
          task={t}
          busy={busy}
          onComplete={handleComplete}
          onOpenTask={onOpenTask}
        />
      ))}

      {/* Create task — only shown when the dashboard is the
          current user's own view (or engagement-scoped + canCreate). */}
      {canCreate && work && (
        <div
          data-testid="my-work-create"
          style={{
            borderTop: "1px solid #e5e7eb",
            paddingTop: 10,
            display: "flex",
            gap: 6,
            alignItems: "center",
          }}
        >
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="New task title…"
            data-testid="my-work-create-title"
            disabled={busy}
            style={{
              flex: 1,
              padding: "4px 6px",
              fontSize: 12,
              border: "1px solid #d1d5db",
              borderRadius: 4,
            }}
          />
          {sessionId ? (
            // Engagement-scoped — implicit session.
            <button
              type="button"
              onClick={() => {
                setCreatingFor(sessionId);
                void handleCreate();
              }}
              disabled={busy || !newTitle.trim()}
              data-testid="my-work-create-submit"
              style={{
                padding: "4px 10px",
                background: newTitle.trim() ? "#111827" : "#9ca3af",
                color: "white",
                border: 0,
                borderRadius: 4,
                fontSize: 12,
                cursor: newTitle.trim() ? "pointer" : "not-allowed",
              }}
            >
              Add task
            </button>
          ) : (
            // Cross-engagement — pick which engagement.
            <>
              <select
                value={creatingFor}
                onChange={(e) => setCreatingFor(e.target.value)}
                data-testid="my-work-create-engagement"
                disabled={busy || buckets.length === 0}
                style={{ padding: "4px 6px", fontSize: 12 }}
              >
                <option value="">on engagement…</option>
                {buckets.map((b) => (
                  <option key={b.session_id} value={b.session_id}>
                    {b.engagement_title || b.session_id.slice(0, 8)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={busy || !newTitle.trim() || !creatingFor}
                data-testid="my-work-create-submit"
                style={{
                  padding: "4px 10px",
                  background:
                    newTitle.trim() && creatingFor ? "#111827" : "#9ca3af",
                  color: "white",
                  border: 0,
                  borderRadius: 4,
                  fontSize: 12,
                  cursor:
                    newTitle.trim() && creatingFor ? "pointer" : "not-allowed",
                }}
              >
                Add task
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------


interface BucketProps {
  bucket: EngagementBucket;
  busy: boolean;
  onComplete: (id: string) => void;
  onOpenTask?: (t: UnifiedTask) => void;
}

function EngagementBucketView({ bucket, busy, onComplete, onOpenTask }: BucketProps) {
  return (
    <div
      data-testid={`my-work-engagement-${bucket.session_id}`}
      style={{ display: "flex", flexDirection: "column", gap: 4 }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          padding: "2px 0",
        }}
      >
        <strong style={{ fontSize: 12, color: "#111827" }}>
          {bucket.engagement_title || bucket.session_id.slice(0, 8)}
        </strong>
        <span style={{ fontSize: 10, color: "#6b7280" }}>
          {bucket.counts.total} task{bucket.counts.total === 1 ? "" : "s"}
          {bucket.counts.high > 0 && (
            <span style={{ color: "#991b1b", fontWeight: 700 }}>
              {" · "}
              {bucket.counts.high} high
            </span>
          )}
        </span>
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0,
                    display: "flex", flexDirection: "column", gap: 3 }}>
        {bucket.tasks.map((t) => (
          <li key={`${t.source}-${t.source_ref}`}>
            <TaskRow
              task={t}
              busy={busy}
              onComplete={onComplete}
              onOpenTask={onOpenTask}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}


interface TaskRowProps {
  task: UnifiedTask;
  busy: boolean;
  onComplete: (id: string) => void;
  onOpenTask?: (t: UnifiedTask) => void;
}

function TaskRow({ task, busy, onComplete, onOpenTask }: TaskRowProps) {
  const tone = PRIORITY_TONE[task.priority] || PRIORITY_TONE.medium;
  const isExplicit = task.source === "explicit";

  return (
    <div
      data-testid={`my-work-task-${task.source_ref}`}
      data-priority={task.priority}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 8px",
        border: `1px solid ${tone.border}`,
        background: tone.bg,
        borderRadius: 4,
        fontSize: 12,
      }}
    >
      {isExplicit ? (
        <input
          type="checkbox"
          data-testid={`my-work-complete-${task.source_ref}`}
          onChange={() => onComplete(task.source_ref)}
          disabled={busy}
        />
      ) : (
        <span aria-hidden style={{ width: 14, textAlign: "center", color: tone.fg }}>
          {TYPE_ICON[task.task_type] || "•"}
        </span>
      )}
      <button
        type="button"
        onClick={() => onOpenTask?.(task)}
        disabled={!onOpenTask}
        data-testid={`my-work-open-${task.source_ref}`}
        style={{
          flex: 1,
          background: "transparent",
          border: 0,
          padding: 0,
          color: tone.fg,
          fontSize: 12,
          textAlign: "left",
          cursor: onOpenTask ? "pointer" : "default",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {task.summary}
      </button>
      <span style={{ fontSize: 9, color: tone.fg, fontWeight: 700,
                     letterSpacing: 0.5, textTransform: "uppercase" }}>
        {task.priority}
      </span>
    </div>
  );
}
