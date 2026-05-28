"use client";

// Per-claim verification feedback — Phase 5 / Week 24 / Day 3.
// A one-click "is this verified correctly?" affordance next to each
// claim. Thumbs-up = correct; thumbs-down opens a tiny popover to say
// whether it was a wrong-supported (dangerous) or wrong-flagged
// (over-caution) call, plus an optional note. Optional + one-click —
// friction kills response rate.

import { useState } from "react";

import {
  postClaimFeedback,
  type ClaimAssessment,
} from "@/lib/api/pilotFeedback";
import { usePilotFeedbackOptional } from "./PilotFeedbackContext";

interface Props {
  claimId: string;
  /** The verdict shown to the consultant, frozen with the feedback. */
  verdict?: string;
  compact?: boolean;
}

export default function ClaimVerificationFeedback({ claimId, verdict, compact }: Props) {
  const ctx = usePilotFeedbackOptional();
  const [sent, setSent] = useState<ClaimAssessment | null>(null);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  if (!ctx) return null;

  const send = async (assessment: ClaimAssessment) => {
    setBusy(true);
    try {
      await postClaimFeedback(ctx.sessionId, claimId, {
        consultant_assessment: assessment,
        verdict_at_feedback: verdict,
        note: note.trim() || undefined,
      });
      setSent(assessment);
      setOpen(false);
    } catch {
      // Silent — feedback is best-effort; never block the reader.
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <span className="ml-1 text-xs text-emerald-700" title="Thanks — feedback recorded">
        ✓
      </span>
    );
  }

  return (
    <span className="relative ml-1 inline-flex items-center gap-0.5">
      <button
        type="button"
        disabled={busy}
        onClick={() => send("correct")}
        title="Verification looks correct"
        data-testid={`claim-verify-up-${claimId}`}
        className="text-xs text-argus-secondary hover:text-emerald-700"
      >
        👍
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => setOpen((v) => !v)}
        title="Verification looks wrong"
        data-testid={`claim-verify-down-${claimId}`}
        className="text-xs text-argus-secondary hover:text-red-700"
      >
        👎
      </button>
      {!compact && <span className="text-[10px] text-argus-secondary">verified?</span>}

      {open && (
        <span className="absolute left-0 top-5 z-10 w-56 rounded-argus border border-argus-border-subtle bg-surface p-2 shadow-lg">
          <span className="mb-1 block text-[11px] font-medium text-argus-secondary">
            What&apos;s wrong?
          </span>
          <span className="flex flex-col gap-1">
            <button
              type="button"
              disabled={busy}
              onClick={() => send("wrong_supported")}
              className="rounded px-2 py-1 text-left text-xs hover:bg-elevated"
            >
              Marked supported but isn&apos;t (false positive)
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => send("wrong_flagged")}
              className="rounded px-2 py-1 text-left text-xs hover:bg-elevated"
            >
              Flagged but is actually fine (over-caution)
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => send("unsure")}
              className="rounded px-2 py-1 text-left text-xs hover:bg-elevated"
            >
              Unsure
            </button>
          </span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note"
            className="mt-1 w-full rounded border border-argus-border-subtle px-2 py-1 text-xs"
          />
        </span>
      )}
    </span>
  );
}
