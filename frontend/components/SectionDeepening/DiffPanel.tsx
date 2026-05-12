"use client";

/**
 * DiffPanel — Phase 2 / Week 9 / Day 3.
 *
 * Two-column side-by-side: Original (left) | Deepened (right).
 * Each side is rendered as flattened text segments so we can apply
 * a word-level diff and highlight what's new (green left-border on
 * the right) vs. what was removed (strikethrough on the left).
 *
 * The word-diff is intentionally simple — split on whitespace,
 * compare with longest-common-subsequence in O(n·m). No external
 * library; for sections under ~10KB this is fast enough that
 * adding diff-match-patch isn't worth the bundle weight.
 *
 * The new-citations callout pulls claim_ids that appear on the
 * deepened side but not the original. (The backend already
 * computes ``new_claim_ids`` on the deepening row; we display
 * those directly without trying to find source breadcrumbs —
 * Phase 4 polish can join chunk metadata.)
 */

import { useState } from "react";

import {
  acceptDeepening,
  DeepeningDetail,
  rejectDeepening,
  sectionDisplayName,
} from "@/lib/api/sectionDeepening";

export interface DiffPanelProps {
  sessionId: string;
  detail: DeepeningDetail;
  /** Called after a successful accept; the host should refresh
   * the memo from ``new_payload``. */
  onAccepted: (newPayload: Record<string, unknown>) => void;
  /** Called after a successful reject. */
  onRejected: () => void;
  /** "Save for later" — closes without accepting/rejecting. */
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Flatten any section value into a single string for word-diffing.
// Lists become space-joined; dicts get key:value lines.
// ---------------------------------------------------------------------------

function flatten(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.map((x) => flatten(x)).join(" \n• ");
  }
  if (typeof value === "object") {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      parts.push(`${k}: ${flatten(v)}`);
    }
    return parts.join("\n");
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// Word-level LCS diff. Returns two arrays of segments
// (text, status) where status ∈ {"same", "added", "removed"}.
// ---------------------------------------------------------------------------

type DiffSeg = { text: string; status: "same" | "added" | "removed" };

function wordDiff(originalText: string, deepenedText: string): {
  leftSegs: DiffSeg[];
  rightSegs: DiffSeg[];
} {
  const oWords = originalText.split(/(\s+)/).filter(Boolean);
  const dWords = deepenedText.split(/(\s+)/).filter(Boolean);
  const m = oWords.length;
  const n = dWords.length;
  // LCS length table.
  const lcs: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < n; j++) {
      if (oWords[i] === dWords[j]) {
        lcs[i + 1][j + 1] = lcs[i][j] + 1;
      } else {
        lcs[i + 1][j + 1] = Math.max(lcs[i + 1][j], lcs[i][j + 1]);
      }
    }
  }
  // Backtrack.
  const leftSegs: DiffSeg[] = [];
  const rightSegs: DiffSeg[] = [];
  let i = m;
  let j = n;
  while (i > 0 && j > 0) {
    if (oWords[i - 1] === dWords[j - 1]) {
      leftSegs.unshift({ text: oWords[i - 1], status: "same" });
      rightSegs.unshift({ text: dWords[j - 1], status: "same" });
      i--;
      j--;
    } else if (lcs[i - 1][j] >= lcs[i][j - 1]) {
      leftSegs.unshift({ text: oWords[i - 1], status: "removed" });
      i--;
    } else {
      rightSegs.unshift({ text: dWords[j - 1], status: "added" });
      j--;
    }
  }
  while (i > 0) {
    leftSegs.unshift({ text: oWords[--i], status: "removed" });
  }
  while (j > 0) {
    rightSegs.unshift({ text: dWords[--j], status: "added" });
  }
  return { leftSegs, rightSegs };
}

// ---------------------------------------------------------------------------
// One side of the diff column.
// ---------------------------------------------------------------------------

function DiffColumn({
  label,
  segs,
  side,
}: {
  label: string;
  segs: DiffSeg[];
  side: "left" | "right";
}) {
  return (
    <div
      data-testid={`diff-column-${side}`}
      className="flex-1 overflow-auto rounded border border-argus-border-subtle bg-elevated p-3"
    >
      <header className="mb-2 text-[10px] uppercase tracking-wide text-argus-tertiary">
        {label}
      </header>
      <div
        data-testid={`diff-text-${side}`}
        className="whitespace-pre-wrap text-[12px] leading-relaxed text-argus-primary"
      >
        {segs.map((seg, idx) => {
          if (seg.status === "same") {
            return <span key={idx}>{seg.text}</span>;
          }
          if (seg.status === "added") {
            return (
              <span
                key={idx}
                data-testid="diff-added"
                className="border-l-2 border-argus-firm-border bg-argus-firm-bg/40 pl-0.5 text-argus-firm"
              >
                {seg.text}
              </span>
            );
          }
          // removed
          return (
            <span
              key={idx}
              data-testid="diff-removed"
              className="text-argus-contested line-through"
            >
              {seg.text}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel.
// ---------------------------------------------------------------------------

export default function DiffPanel({
  sessionId,
  detail,
  onAccepted,
  onRejected,
  onClose,
}: DiffPanelProps) {
  const [submitting, setSubmitting] = useState<"accept" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const originalText = flatten(detail.original_section_json);
  const deepenedText = flatten(detail.deepened_section_json);
  const { leftSegs, rightSegs } = wordDiff(originalText, deepenedText);

  const display = sectionDisplayName(detail.section_path);

  const onAccept = async () => {
    if (submitting) return;
    setSubmitting("accept");
    setError(null);
    try {
      const res = await acceptDeepening(sessionId, detail.id);
      if (res.status === "accepted" && res.new_payload) {
        onAccepted(res.new_payload);
      } else if (res.status === "already_accepted") {
        // Idempotent — backend says it was already done. Treat as success.
        onAccepted(res.new_payload || {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(null);
    }
  };

  const onReject = async () => {
    if (submitting) return;
    setSubmitting("reject");
    setError(null);
    try {
      await rejectDeepening(sessionId, detail.id);
      onRejected();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(null);
    }
  };

  return (
    <div
      data-testid="diff-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="diff-panel-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="flex h-[88vh] w-[1100px] max-w-[96vw] flex-col rounded-md border border-argus-border-subtle bg-surface p-5 shadow-lg">
        <header className="mb-3 flex items-baseline justify-between">
          <h3
            id="diff-panel-title"
            className="font-serif text-[18px] font-semibold text-argus-primary"
          >
            Deepened section: {display}
          </h3>
          <span className="font-mono text-[10px] text-argus-tertiary">
            {detail.section_path}
          </span>
        </header>

        <div
          data-testid="cost-row"
          className="mb-3 flex items-center gap-4 rounded border border-argus-border-subtle bg-elevated px-3 py-1.5 text-[11px] text-argus-secondary"
        >
          <span>${(detail.cost_usd ?? 0).toFixed(2)}</span>
          <span>·</span>
          <span>{(detail.wall_seconds ?? 0).toFixed(0)} seconds</span>
          <span>·</span>
          <span>{detail.new_evidence_chunks_used ?? 0} new evidence chunks</span>
          <span>·</span>
          <span>{(detail.new_claim_ids ?? []).length} new claims</span>
        </div>

        <div className="flex flex-1 gap-3 overflow-hidden">
          <DiffColumn label="Original" segs={leftSegs} side="left" />
          <DiffColumn label="Deepened" segs={rightSegs} side="right" />
        </div>

        {detail.new_claim_ids && detail.new_claim_ids.length > 0 ? (
          <section
            data-testid="new-citations"
            className="mt-3 rounded border border-argus-border-subtle bg-elevated p-3"
          >
            <header className="mb-1 text-[10px] uppercase tracking-wide text-argus-tertiary">
              New citations ({detail.new_claim_ids.length})
            </header>
            <ul className="flex flex-wrap gap-1">
              {detail.new_claim_ids.map((cid) => (
                <li
                  key={cid}
                  className="rounded border border-argus-border-subtle bg-surface px-1.5 py-0.5 font-mono text-[10px] text-argus-tertiary"
                >
                  {cid}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {error ? (
          <p
            data-testid="diff-error"
            className="mt-2 text-[12px] text-argus-contested"
          >
            {error}
          </p>
        ) : null}

        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={!!submitting}
            className="rounded border border-argus-border-subtle bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:bg-elevated disabled:opacity-50"
          >
            Save for later
          </button>
          <button
            type="button"
            data-testid="reject-button"
            onClick={onReject}
            disabled={!!submitting}
            className="rounded border border-argus-contested-border bg-argus-contested-bg px-3 py-1.5 text-[12px] text-argus-contested hover:opacity-90 disabled:opacity-50"
          >
            {submitting === "reject" ? "Rejecting…" : "Reject"}
          </button>
          <button
            type="button"
            data-testid="accept-button"
            onClick={onAccept}
            disabled={!!submitting}
            className="rounded border border-argus-firm-border bg-argus-firm-bg px-3 py-1.5 text-[12px] font-semibold text-argus-firm hover:opacity-90 disabled:opacity-50"
          >
            {submitting === "accept" ? "Accepting…" : "Accept and merge"}
          </button>
        </div>
      </div>
    </div>
  );
}
