"use client";

import { useMemo, useState } from "react";

import { ReviewBlockedError, resolvePointer, submitForReview } from "@/lib/api/review";
import type { ReviewFeedback, SectionPointer } from "@/lib/api/review";

interface Props {
  sessionId: string;
  reviewRecordId: string;
  feedback: ReviewFeedback;
  onResolved: () => void;
  onResubmitted: () => void;
  /** Optional callback to scroll the MemoEditor to a clicked section
   *  path. The integration is best-effort — the W9 section addressing
   *  resolves the path; the MemoEditor's section anchors are added in
   *  a follow-up. */
  onJumpToSection?: (sectionPath: string) => void;
}

/**
 * Consultant-side view when the engagement is in ``changes_requested``.
 *
 * Renders the reviewer's overall feedback prominently, lists each
 * section pointer with a resolve toggle, and shows the "Resubmit for
 * review" button. The button is disabled (with a clear tooltip)
 * until every blocking/major pointer is resolved.
 *
 * Minor pointers don't gate. They render as advisory rows next to
 * the resolve toggle (consultant can address or skip).
 */
export default function ChangesRequestedPanel({
  sessionId,
  reviewRecordId,
  feedback,
  onResolved,
  onResubmitted,
  onJumpToSection,
}: Props) {
  // Local copy of the pointer-resolution state so the UI reflects the
  // pending toggle without waiting for a parent re-fetch.
  const [pointers, setPointers] = useState<SectionPointer[]>(
    feedback.section_pointers,
  );
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [resubmitBusy, setResubmitBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockedPaths, setBlockedPaths] = useState<string[]>([]);

  const blockingUnresolved = useMemo(
    () =>
      pointers
        .filter((p) => (p.severity === "major" || p.severity === "blocking") && !p.resolved)
        .map((p) => p.section_path),
    [pointers],
  );
  const resubmitDisabled = blockingUnresolved.length > 0 || resubmitBusy;

  const toggleResolved = async (sectionPath: string, currentlyResolved: boolean) => {
    if (currentlyResolved) {
      // The API doesn't support "un-resolve" — pointers move one way.
      // We disable the toggle in the UI for resolved rows.
      return;
    }
    setBusyPath(sectionPath);
    setError(null);
    try {
      await resolvePointer(sessionId, reviewRecordId, sectionPath);
      setPointers((prev) =>
        prev.map((p) =>
          p.section_path === sectionPath
            ? { ...p, resolved: true, resolved_at: new Date().toISOString() }
            : p,
        ),
      );
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resolve failed");
    } finally {
      setBusyPath(null);
    }
  };

  const resubmit = async () => {
    if (resubmitDisabled) return;
    setResubmitBusy(true);
    setError(null);
    setBlockedPaths([]);
    try {
      await submitForReview(sessionId);
      onResubmitted();
    } catch (e) {
      if (e instanceof ReviewBlockedError) {
        setBlockedPaths(e.blocking_pointer_paths);
        setError(e.message);
      } else {
        setError(e instanceof Error ? e.message : "Resubmit failed");
      }
    } finally {
      setResubmitBusy(false);
    }
  };

  const sevTone = (sev: SectionPointer["severity"]): string => {
    if (sev === "blocking") return "bg-red-50 text-red-700 border-red-200";
    if (sev === "major") return "bg-amber-50 text-amber-700 border-amber-200";
    return "bg-elevated text-argus-tertiary border-argus-border-subtle";
  };

  return (
    <section
      data-testid="changes-requested-panel"
      className="rounded-md border border-amber-200 bg-amber-50/40 p-3 text-[12px]"
    >
      <h3 className="font-serif text-[14px] font-semibold text-amber-800 mb-2">
        Reviewer requested changes
      </h3>

      <div className="rounded-sm border border-argus-border-subtle bg-surface p-2 mb-3">
        <p
          data-testid="overall-feedback"
          className="text-argus-primary whitespace-pre-wrap text-[12px]"
        >
          {feedback.overall_note}
        </p>
        <p className="text-argus-tertiary text-[10px] uppercase tracking-wide mt-1">
          Severity: {feedback.severity}
        </p>
      </div>

      {pointers.length === 0 ? (
        <p className="text-argus-tertiary text-[11px] italic mb-3">
          No section pointers. Address the overall note and resubmit.
        </p>
      ) : (
        <ul className="space-y-2 mb-3">
          {pointers.map((p) => (
            <li
              key={p.section_path}
              data-testid={`pointer-${p.section_path}`}
              className={`rounded-sm border p-2 ${sevTone(p.severity)}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] uppercase tracking-wide font-semibold">
                  {p.severity}
                </span>
                <button
                  type="button"
                  data-testid={`jump-${p.section_path}`}
                  onClick={() => onJumpToSection?.(p.section_path)}
                  className="font-mono text-[11px] text-argus-primary underline hover:opacity-80"
                  title={`Jump to ${p.section_path}`}
                >
                  {p.section_path}
                </button>
                <span className="ml-auto">
                  {p.resolved ? (
                    <span
                      data-testid={`resolved-${p.section_path}`}
                      className="text-emerald-700 text-[10px] uppercase tracking-wide"
                    >
                      Resolved
                    </span>
                  ) : (
                    <button
                      type="button"
                      data-testid={`resolve-${p.section_path}`}
                      onClick={() => toggleResolved(p.section_path, p.resolved)}
                      disabled={busyPath === p.section_path}
                      className="rounded-sm border border-emerald-600 bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] hover:bg-emerald-100 disabled:opacity-60"
                    >
                      {busyPath === p.section_path ? "Saving…" : "Mark resolved"}
                    </button>
                  )}
                </span>
              </div>
              <p className="text-argus-primary text-[11px] whitespace-pre-wrap">
                {p.note}
              </p>
            </li>
          ))}
        </ul>
      )}

      {error ? (
        <p data-testid="changes-error" className="text-red-700 text-[11px] mb-2">
          {error}
          {blockedPaths.length > 0 ? (
            <span className="block mt-1">
              Still blocking: {blockedPaths.join(", ")}
            </span>
          ) : null}
        </p>
      ) : null}

      <button
        type="button"
        data-testid="resubmit-button"
        disabled={resubmitDisabled}
        onClick={resubmit}
        title={
          resubmitDisabled
            ? `Resolve all major / blocking pointers first: ${blockingUnresolved.join(", ")}`
            : "Resubmit for review"
        }
        className="rounded-sm border border-argus-primary bg-argus-primary text-argus-inverse px-2 py-1 text-[11px] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {resubmitBusy ? "Resubmitting…" : "Resubmit for review"}
      </button>
    </section>
  );
}
