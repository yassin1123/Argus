"use client";

interface Props {
  /** Whether the dialog is visible. The parent controls visibility
   *  by checking the engagement's review_state before triggering an
   *  edit (memo write / section-deepening) — locked states should
   *  prompt before the action. */
  open: boolean;
  /** Short label of the action being attempted, surfaced in the
   *  warning copy. E.g. "section deepening" or "edit memo". */
  actionLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Per W15/D4 hard rule: the auto-revert path must NOT be silent.
 * The consultant has to confirm they understand editing a locked
 * (approved / delivered) engagement will revert it to draft and
 * require re-review.
 *
 * This dialog renders when the parent detects the lock + an
 * edit-intent. Confirming proceeds with the edit (the W15/D2 service
 * fires the AUTO_REVERT transition on the next deepen / accept call).
 * Cancelling drops the user back to the workspace unchanged.
 */
export default function AutoRevertConfirmDialog({
  open,
  actionLabel = "editing this engagement",
  onConfirm,
  onCancel,
}: Props) {
  if (!open) return null;
  return (
    <div
      data-testid="auto-revert-dialog"
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-md border border-amber-300 bg-surface p-4 text-[12px]">
        <h2 className="font-serif text-[16px] font-semibold mb-2 text-amber-800">
          Engagement is approved
        </h2>
        <p className="text-argus-primary mb-3">
          This engagement was approved and is currently locked for editing.
          Proceeding with <strong>{actionLabel}</strong> will:
        </p>
        <ul className="text-argus-secondary mb-3 list-disc pl-5">
          <li>Revert the engagement state to <strong>draft</strong>.</li>
          <li>Flag every generated artifact (1-pager, deck, model, email,
              interview guide) as stale.</li>
          <li>Require a fresh review cycle before the next delivery.</li>
        </ul>
        <p className="text-argus-tertiary text-[11px] mb-3">
          The review history is preserved — the auto-revert event lands
          on the timeline so the team sees what happened.
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            data-testid="auto-revert-cancel"
            onClick={onCancel}
            className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[11px] hover:border-argus-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="auto-revert-confirm"
            onClick={onConfirm}
            className="rounded-sm border border-amber-700 bg-amber-700 text-white px-2 py-1 text-[11px] hover:bg-amber-800"
          >
            Continue and revert to draft
          </button>
        </div>
      </div>
    </div>
  );
}
