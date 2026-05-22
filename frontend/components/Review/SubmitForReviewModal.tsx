"use client";

import { useEffect, useMemo, useState } from "react";

import { listEngagementMembers } from "@/lib/api";
import { submitForReview } from "@/lib/api/review";
import type { EngagementMember } from "@/lib/types";

interface Props {
  sessionId: string;
  currentUserId: string;
  allowSelfApproval?: boolean;
  /** Called after a successful submit (refresh the badge / panel). */
  onSubmitted: () => void;
  onCancel: () => void;
}

/**
 * Two-step modal:
 *   1. Pick a reviewer from the engagement team (admin role or any
 *      member; self excluded unless the firm allows self-approval).
 *   2. Optional note + confirm.
 *
 * Hard rule (per W15/D4 spec): we don't show the consultant themselves
 * as a reviewer unless ``allowSelfApproval`` is true — UI enforces
 * segregation of duties visibly, not only at the API.
 */
export default function SubmitForReviewModal({
  sessionId,
  currentUserId,
  allowSelfApproval = false,
  onSubmitted,
  onCancel,
}: Props) {
  const [members, setMembers] = useState<EngagementMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewerId, setReviewerId] = useState<string>("");
  const [note, setNote] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    listEngagementMembers(sessionId)
      .then((list) => {
        if (!mounted) return;
        setMembers(list);
      })
      .catch((e) => {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load team");
      });
    return () => { mounted = false; };
  }, [sessionId]);

  const eligible: EngagementMember[] = useMemo(() => {
    if (!members) return [];
    return members.filter((m) => {
      // ``lead`` and ``member`` can both serve as reviewers. The
      // service-layer authz enforces "admin OR explicitly-assigned
      // reviewer"; assignment is what we're doing here, so a member
      // is a valid pick.
      if (!allowSelfApproval && m.user_id === currentUserId) return false;
      return true;
    });
  }, [members, currentUserId, allowSelfApproval]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await submitForReview(sessionId, reviewerId ? { reviewer_id: reviewerId } : {});
      onSubmitted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="submit-for-review-modal"
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-md border border-argus-border-subtle bg-surface p-4 text-[12px] text-argus-primary shadow-lg">
        <h2 className="font-serif text-[16px] font-semibold mb-2">Submit for review</h2>
        <p className="text-argus-secondary mb-3">
          Move this engagement into <strong>in review</strong>. The reviewer
          will be able to approve or request changes.
        </p>

        <label className="block mb-1 text-argus-tertiary text-[11px] uppercase tracking-wide">
          Reviewer
        </label>
        {members === null && !error ? (
          <p className="text-argus-tertiary text-[11px] py-1">Loading team…</p>
        ) : eligible.length === 0 ? (
          <p
            data-testid="no-eligible-reviewer"
            className="text-amber-700 text-[11px] py-1"
          >
            No eligible reviewer on this engagement. Add a teammate via the
            Team panel, or ask a firm admin to flip self-approval on.
          </p>
        ) : (
          <select
            data-testid="reviewer-picker"
            value={reviewerId}
            onChange={(e) => setReviewerId(e.target.value)}
            disabled={busy}
            className="w-full rounded-sm border border-argus-border-subtle bg-elevated px-2 py-1 mb-3"
          >
            <option value="">(no specific reviewer — any firm admin)</option>
            {eligible.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name || m.email} · {m.role}
              </option>
            ))}
          </select>
        )}

        <label className="block mb-1 text-argus-tertiary text-[11px] uppercase tracking-wide">
          Note to reviewer (optional)
        </label>
        <textarea
          data-testid="reviewer-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
          rows={3}
          className="w-full rounded-sm border border-argus-border-subtle bg-elevated px-2 py-1 mb-3 text-[12px]"
          placeholder="e.g. Please focus the review on the synergy estimate."
        />

        {error ? (
          <p data-testid="submit-error" className="text-red-700 text-[11px] mb-2">{error}</p>
        ) : null}

        <div className="flex justify-end gap-2 mt-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[11px] hover:border-argus-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="submit-confirm"
            onClick={submit}
            disabled={busy}
            className="rounded-sm border border-argus-primary bg-argus-primary text-argus-inverse px-2 py-1 text-[11px] hover:opacity-90 disabled:opacity-60"
          >
            {busy ? "Submitting…" : "Submit for review"}
          </button>
        </div>
      </div>
    </div>
  );
}
