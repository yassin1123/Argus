"use client";

import { useState } from "react";

import type { ReviewFeedback, ReviewHistoryEntry } from "@/lib/api/review";

interface Props {
  history: ReviewHistoryEntry[];
}

const ACTION_LABELS: Record<string, string> = {
  submit_for_review: "Submitted for review",
  approve: "Approved",
  request_changes: "Requested changes",
  resubmit: "Resubmitted",
  mark_delivered: "Marked delivered",
  reopen: "Reopened",
  auto_revert: "Auto-reverted (edit detected)",
};

function relTime(iso: string): string {
  try {
    const t = new Date(iso).getTime();
    const dt = Date.now() - t;
    const m = Math.floor(dt / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  } catch {
    return "";
  }
}

function asReviewFeedback(fb: ReviewFeedback | string | null): ReviewFeedback | null {
  if (!fb) return null;
  if (typeof fb === "string") {
    return { overall_note: fb, section_pointers: [], severity: "major" };
  }
  return fb;
}

/**
 * Chronological timeline of the engagement's review_records. Each
 * entry is a one-liner with a "details" expander; request_changes
 * entries reveal the structured feedback + per-pointer resolution
 * status when expanded.
 */
export default function ReviewHistory({ history }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (!history || history.length === 0) {
    return (
      <section
        data-testid="review-history"
        className="rounded-md border border-argus-border-subtle bg-surface p-3 text-[12px]"
      >
        <h3 className="font-serif text-[14px] font-semibold mb-2 text-argus-primary">
          Review history
        </h3>
        <p
          data-testid="empty-history"
          className="text-argus-tertiary text-[11px] italic"
        >
          No review actions yet. Submit the engagement to start the cycle.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="review-history"
      className="rounded-md border border-argus-border-subtle bg-surface p-3 text-[12px]"
    >
      <h3 className="font-serif text-[14px] font-semibold mb-2 text-argus-primary">
        Review history
      </h3>
      <ol className="space-y-2">
        {history.map((entry) => {
          const fb = asReviewFeedback(entry.feedback);
          const expanded = openId === entry.id;
          const expandable = entry.action === "request_changes" && fb !== null;
          return (
            <li
              key={entry.id}
              data-testid={`review-history-entry-${entry.id}`}
              className="rounded-sm border border-argus-border-subtle bg-elevated p-2"
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] uppercase tracking-wide text-argus-tertiary mt-0.5">
                  {relTime(entry.created_at)}
                </span>
                <div className="flex-1">
                  <p className="text-[11px] text-argus-primary">
                    <strong>{ACTION_LABELS[entry.action] ?? entry.action}</strong>
                    {" · "}
                    <span className="font-mono text-[10px] text-argus-tertiary">
                      {entry.from_state} → {entry.to_state}
                    </span>
                  </p>
                  {entry.actor_id ? (
                    <p className="text-[10px] text-argus-tertiary">
                      actor: <span className="font-mono">{entry.actor_id.slice(0, 8)}…</span>
                      {entry.reviewer_id ? (
                        <>
                          {" · "}
                          reviewer: <span className="font-mono">{entry.reviewer_id.slice(0, 8)}…</span>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                </div>
                {expandable ? (
                  <button
                    type="button"
                    data-testid={`expand-${entry.id}`}
                    onClick={() => setOpenId(expanded ? null : entry.id)}
                    className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-0.5 text-[10px] hover:border-argus-primary"
                  >
                    {expanded ? "Hide" : "Details"}
                  </button>
                ) : null}
              </div>

              {expandable && expanded && fb ? (
                <div
                  data-testid={`feedback-details-${entry.id}`}
                  className="mt-2 rounded-sm border border-argus-border-subtle bg-surface p-2"
                >
                  <p className="text-[11px] text-argus-primary whitespace-pre-wrap mb-1">
                    {fb.overall_note}
                  </p>
                  <p className="text-[10px] uppercase tracking-wide text-argus-tertiary mb-2">
                    Severity: {fb.severity}
                  </p>
                  {fb.section_pointers.length === 0 ? (
                    <p className="text-[10px] italic text-argus-tertiary">
                      No section pointers.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {fb.section_pointers.map((p) => (
                        <li
                          key={p.section_path}
                          className="text-[10px] text-argus-secondary"
                        >
                          <span className="font-mono">{p.section_path}</span>
                          <span className="ml-2 text-argus-tertiary">[{p.severity}]</span>
                          <span className="ml-2">
                            {p.resolved ? (
                              <span className="text-emerald-700">resolved</span>
                            ) : (
                              <span className="text-amber-700">open</span>
                            )}
                          </span>
                          <p className="text-argus-secondary mt-0.5 whitespace-pre-wrap">
                            {p.note}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
