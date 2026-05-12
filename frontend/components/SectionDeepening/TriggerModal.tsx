"use client";

/**
 * TriggerModal — Phase 2 / Week 9 / Day 2.
 *
 * Opens when the consultant clicks "Deepen" on a section. Collects an
 * optional depth_directive, fires the deepening, and signals success
 * (carrying the new ``deepening_id`` upstream). The host component
 * swaps to the StatusPanel after a successful trigger.
 *
 * Functional-first; polish in Phase 4. The modal uses inline styling
 * matching the existing Argus design tokens (argus-primary,
 * argus-border-subtle, surface / elevated, etc.) — no new tokens
 * introduced.
 */

import { useState } from "react";

import {
  sectionDisplayName,
  triggerDeepening,
} from "@/lib/api/sectionDeepening";

export interface TriggerModalProps {
  sessionId: string;
  sectionPath: string;
  onTriggered: (deepeningId: string, sectionPath: string, directive: string) => void;
  onCancel: () => void;
}

export default function TriggerModal({
  sessionId,
  sectionPath,
  onTriggered,
  onCancel,
}: TriggerModalProps) {
  const [directive, setDirective] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const display = sectionDisplayName(sectionPath);

  const onSubmit = async () => {
    if (!sectionPath.trim()) {
      setError("Section path is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await triggerDeepening(sessionId, sectionPath, directive.trim() || undefined);
      // Backend POST returns { status: "queued", session_id, section_path,
      // depth_directive } but the deepening_id lands later when the row
      // is inserted. The list endpoint is the simplest way to grab it —
      // most recently created run for this session matching the path.
      // Day 3+ can switch to returning deepening_id directly.
      const { listDeepenings } = await import("@/lib/api/sectionDeepening");
      const all = await listDeepenings(sessionId);
      const match = all.find(
        (d) => d.section_path === sectionPath && (d.status === "queued" || d.status === "running"),
      );
      if (!match) {
        throw new Error("Deepening was triggered but the row did not appear in the list");
      }
      onTriggered(match.id, sectionPath, directive.trim());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  return (
    <div
      data-testid="trigger-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="trigger-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="w-[480px] max-w-[92vw] rounded-md border border-argus-border-subtle bg-surface p-5 shadow-lg">
        <header className="mb-3">
          <h3
            id="trigger-modal-title"
            className="font-serif text-[18px] font-semibold text-argus-primary"
          >
            Deepen section: {display}
          </h3>
          <p className="mt-1 text-[12px] text-argus-tertiary">
            Argus will fetch new evidence and rewrite this section. Other sections are not affected.
          </p>
        </header>

        <label htmlFor="depth-directive" className="block">
          <span className="text-[11px] uppercase tracking-wide text-argus-secondary">
            Why does this section need to be deeper? (Optional but recommended)
          </span>
          <textarea
            id="depth-directive"
            data-testid="depth-directive"
            value={directive}
            onChange={(e) => setDirective(e.target.value)}
            rows={4}
            disabled={submitting}
            placeholder={
              "e.g. The synergy numbers feel generic — base them on comparable transactions.\n" +
              "Or: Add more detail on regulatory risk.\n" +
              "Or: Quantify the timing — show me which quarter each milestone lands."
            }
            className="mt-1 w-full rounded border border-argus-border-subtle bg-elevated p-2 text-[13px] text-argus-primary placeholder:text-argus-tertiary focus:outline-none focus:ring-1 focus:ring-argus-firm-border"
            maxLength={4000}
          />
        </label>

        <div className="mt-3 rounded border border-argus-border-subtle bg-elevated px-3 py-2">
          <div className="flex items-baseline justify-between text-[11px] text-argus-tertiary">
            <span>Estimated cost: $0.15-0.40</span>
            <span>Estimated time: 30-90 seconds</span>
          </div>
        </div>

        {error ? (
          <p data-testid="trigger-error" className="mt-2 text-[12px] text-argus-contested">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded border border-argus-border-subtle bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:bg-elevated disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting}
            data-testid="trigger-submit"
            className="rounded border border-argus-firm-border bg-argus-firm-bg px-3 py-1.5 text-[12px] font-semibold text-argus-firm hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? "Triggering…" : "Run deepening"}
          </button>
        </div>
      </div>
    </div>
  );
}
