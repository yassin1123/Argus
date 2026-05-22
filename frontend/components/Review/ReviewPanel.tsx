"use client";

import { useState } from "react";

import { approveReview, requestChanges } from "@/lib/api/review";
import type { FeedbackSeverity } from "@/lib/api/review";

interface SectionPointerDraft {
  section_path: string;
  note: string;
  severity: FeedbackSeverity;
}

interface Props {
  sessionId: string;
  /** Section paths the reviewer can attach pointers to. Sourced from
   *  the writer payload — caller passes the de-nested key list. */
  availableSectionPaths: string[];
  /** Hide the panel entirely when the viewing user isn't allowed
   *  to act (author + segregation-of-duties, non-admin non-reviewer). */
  visible: boolean;
  onActed: () => void;
}

const SEVERITIES: FeedbackSeverity[] = ["minor", "major", "blocking"];

/**
 * Reviewer panel — Approve or Request changes with structured feedback.
 *
 * The "Approve" button fires a confirmation banner first so a partner
 * doesn't approve in one click and inadvertently lock the engagement.
 * The "Request changes" form lets the reviewer add an overall note +
 * an arbitrary number of section pointers, each with its own severity.
 *
 * Hard rule visibility: the parent renders this panel only when the
 * viewing user is allowed to review (admin OR assigned-reviewer, AND
 * not the author unless allow_self_approval is on). The ``visible``
 * prop is the toggle.
 */
export default function ReviewPanel({
  sessionId,
  availableSectionPaths,
  visible,
  onActed,
}: Props) {
  const [mode, setMode] = useState<"idle" | "approving" | "requesting">("idle");
  const [overallNote, setOverallNote] = useState("");
  const [severity, setSeverity] = useState<FeedbackSeverity>("major");
  const [pointers, setPointers] = useState<SectionPointerDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!visible) return null;

  const addPointer = () => {
    const first = availableSectionPaths[0] ?? "";
    setPointers([...pointers, { section_path: first, note: "", severity: "major" }]);
  };

  const updatePointer = (i: number, patch: Partial<SectionPointerDraft>) => {
    setPointers((prev) => prev.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  };

  const removePointer = (i: number) => {
    setPointers((prev) => prev.filter((_, idx) => idx !== i));
  };

  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      await approveReview(sessionId);
      onActed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusy(false);
    }
  };

  const submitChanges = async () => {
    if (overallNote.trim().length === 0) {
      setError("Overall note is required to request changes.");
      return;
    }
    // Drop pointers with empty notes — they're not actionable feedback.
    const cleanPointers = pointers
      .filter((p) => p.note.trim().length > 0 && p.section_path.trim().length > 0)
      .map((p) => ({
        section_path: p.section_path.trim(),
        note: p.note.trim(),
        severity: p.severity,
      }));
    setBusy(true);
    setError(null);
    try {
      await requestChanges(sessionId, {
        overall_note: overallNote.trim(),
        severity,
        section_pointers: cleanPointers,
      });
      onActed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request changes failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="review-panel"
      className="rounded-md border border-argus-border-subtle bg-surface p-3 text-[12px]"
    >
      <h3 className="font-serif text-[14px] font-semibold mb-2 text-argus-primary">
        Review decision
      </h3>

      {mode === "idle" ? (
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="approve-open"
            onClick={() => setMode("approving")}
            className="rounded-sm border border-emerald-700 bg-emerald-50 text-emerald-800 px-2 py-1 text-[11px] hover:bg-emerald-100"
          >
            Approve
          </button>
          <button
            type="button"
            data-testid="request-changes-open"
            onClick={() => setMode("requesting")}
            className="rounded-sm border border-amber-700 bg-amber-50 text-amber-800 px-2 py-1 text-[11px] hover:bg-amber-100"
          >
            Request changes
          </button>
        </div>
      ) : mode === "approving" ? (
        <div data-testid="approve-confirm" className="text-[11px]">
          <p className="text-argus-secondary mb-2">
            <strong>This will lock the engagement</strong> and mark it ready for
            client delivery. Subsequent edits will revert it to draft and
            require re-review.
          </p>
          {error ? <p className="text-red-700 mb-1">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setMode("idle")}
              disabled={busy}
              className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 hover:border-argus-primary"
            >
              Cancel
            </button>
            <button
              type="button"
              data-testid="approve-confirm-button"
              onClick={approve}
              disabled={busy}
              className="rounded-sm border border-emerald-700 bg-emerald-700 text-white px-2 py-1 hover:bg-emerald-800 disabled:opacity-60"
            >
              {busy ? "Approving…" : "Confirm approval"}
            </button>
          </div>
        </div>
      ) : (
        <div data-testid="request-changes-form" className="text-[11px]">
          <label className="block text-argus-tertiary uppercase tracking-wide text-[10px] mb-1">
            Overall feedback
          </label>
          <textarea
            data-testid="overall-note"
            value={overallNote}
            onChange={(e) => setOverallNote(e.target.value)}
            disabled={busy}
            rows={3}
            className="w-full rounded-sm border border-argus-border-subtle bg-elevated px-2 py-1 mb-2 text-[12px]"
            placeholder="What changed and why. The consultant sees this verbatim."
          />

          <label className="block text-argus-tertiary uppercase tracking-wide text-[10px] mb-1">
            Overall severity
          </label>
          <select
            data-testid="severity-select"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as FeedbackSeverity)}
            disabled={busy}
            className="rounded-sm border border-argus-border-subtle bg-elevated px-2 py-1 mb-3"
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          <div className="flex items-center justify-between mb-1">
            <span className="text-argus-tertiary uppercase tracking-wide text-[10px]">
              Section pointers ({pointers.length})
            </span>
            <button
              type="button"
              data-testid="add-pointer"
              onClick={addPointer}
              disabled={busy || availableSectionPaths.length === 0}
              className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-0.5 text-[10px] hover:border-argus-primary disabled:opacity-50"
            >
              + Add pointer
            </button>
          </div>

          {pointers.length === 0 ? (
            <p className="text-argus-tertiary text-[10px] italic mb-2">
              No section pointers. Optional — the overall note is enough on
              its own for light feedback.
            </p>
          ) : (
            <ul className="space-y-2 mb-2">
              {pointers.map((p, i) => (
                <li
                  key={i}
                  data-testid={`pointer-row-${i}`}
                  className="rounded-sm border border-argus-border-subtle p-2"
                >
                  <div className="flex flex-wrap gap-2 mb-1">
                    <select
                      data-testid={`pointer-section-${i}`}
                      value={p.section_path}
                      onChange={(e) => updatePointer(i, { section_path: e.target.value })}
                      className="rounded-sm border border-argus-border-subtle bg-elevated px-1 py-0.5 text-[11px]"
                    >
                      {availableSectionPaths.map((path) => (
                        <option key={path} value={path}>{path}</option>
                      ))}
                    </select>
                    <select
                      data-testid={`pointer-severity-${i}`}
                      value={p.severity}
                      onChange={(e) => updatePointer(i, { severity: e.target.value as FeedbackSeverity })}
                      className="rounded-sm border border-argus-border-subtle bg-elevated px-1 py-0.5 text-[11px]"
                    >
                      {SEVERITIES.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => removePointer(i)}
                      className="text-[10px] text-argus-tertiary hover:text-red-700 ml-auto"
                    >
                      remove
                    </button>
                  </div>
                  <textarea
                    data-testid={`pointer-note-${i}`}
                    value={p.note}
                    onChange={(e) => updatePointer(i, { note: e.target.value })}
                    rows={2}
                    className="w-full rounded-sm border border-argus-border-subtle bg-elevated px-2 py-1 text-[11px]"
                    placeholder="Specific feedback for this section."
                  />
                </li>
              ))}
            </ul>
          )}

          {error ? <p className="text-red-700 mb-1">{error}</p> : null}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setMode("idle")}
              disabled={busy}
              className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 hover:border-argus-primary"
            >
              Cancel
            </button>
            <button
              type="button"
              data-testid="submit-changes"
              onClick={submitChanges}
              disabled={busy}
              className="rounded-sm border border-amber-700 bg-amber-700 text-white px-2 py-1 hover:bg-amber-800 disabled:opacity-60"
            >
              {busy ? "Sending…" : "Send change request"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
