"use client";

import { claimAnchor, useComments } from "./CommentsController";

interface Props {
  claimId: string;
  /** Hide for non-members per W16/D3 hard rule. */
  visible?: boolean;
  /** Inline label override — used in narrow table cells where the
   *  default "Comment" button text would crowd the column. */
  compact?: boolean;
}

/**
 * Inline "Comment on this claim" affordance.
 *
 * Reads counts from :func:`useComments` so it can show an unresolved
 * badge when the claim already has open threads. Clicking opens the
 * panel scoped to ``claim:<claim_id>``. Designed to slot into the
 * memo's claim-citation table cells without disturbing the existing
 * layout — :class:`SchemaDrivenSection` detects ``claim_id`` columns
 * and renders this next to the value.
 */
export default function ClaimCommentAffordance({
  claimId,
  visible = true,
  compact = false,
}: Props) {
  // Defensive: hosted under :class:`CommentsController` but the
  // memo-renderer surface MAY be used in deepening previews / tests
  // outside the controller, in which case useComments would throw.
  // We swallow that and render nothing rather than crash the section.
  let ctx;
  try {
    ctx = useComments();
  } catch {
    return null;
  }
  if (!visible) return null;

  // Claim counts aren't broken out per-claim by the W16/D2 count
  // endpoint (it groups by section_path, not by claim_id). So we
  // render a static affordance and let the panel surface the
  // open count on click. Polish item for Phase 5.
  return (
    <button
      type="button"
      onClick={() => ctx!.openThread(claimAnchor(claimId))}
      data-testid={`claim-comment-${claimId}`}
      title={`Comment on claim ${claimId}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        padding: compact ? "0 4px" : "2px 6px",
        background: "transparent",
        border: 0,
        borderRadius: 6,
        color: "#2563eb",
        cursor: "pointer",
        fontSize: 11,
        textDecoration: "underline dotted",
        textUnderlineOffset: 2,
      }}
    >
      💬 {compact ? "" : "Comment"}
    </button>
  );
}
