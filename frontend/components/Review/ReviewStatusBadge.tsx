"use client";

import type { ReviewState } from "@/lib/api/review";

interface Props {
  state: ReviewState | undefined | null;
  size?: "sm" | "md";
  className?: string;
}

// Each badge variant is a Tailwind colour pair + a short label.
// Picked so the five states are visually distinct under both light
// and dark themes — green for approved, amber for changes_requested,
// blue for in_review, purple for delivered (terminal-good), grey for draft.
const _BADGE_STYLES: Record<ReviewState, { bg: string; text: string; border: string; label: string }> = {
  draft:              { bg: "bg-elevated",        text: "text-argus-tertiary",  border: "border-argus-border-subtle", label: "Draft" },
  in_review:          { bg: "bg-blue-50",         text: "text-blue-700",        border: "border-blue-200",            label: "In review" },
  changes_requested:  { bg: "bg-amber-50",        text: "text-amber-700",       border: "border-amber-200",           label: "Changes requested" },
  approved:           { bg: "bg-emerald-50",      text: "text-emerald-700",     border: "border-emerald-200",         label: "Approved" },
  delivered:          { bg: "bg-purple-50",       text: "text-purple-700",      border: "border-purple-200",          label: "Delivered" },
};

export default function ReviewStatusBadge({ state, size = "sm", className = "" }: Props) {
  // Default to draft when the column hasn't been populated yet (older
  // sessions created before migration 036).
  const resolved: ReviewState = state ?? "draft";
  const style = _BADGE_STYLES[resolved] ?? _BADGE_STYLES.draft;
  const sizeClasses =
    size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]";
  return (
    <span
      data-testid={`review-status-badge-${resolved}`}
      data-state={resolved}
      className={`inline-flex items-center gap-1 rounded-sm border font-medium uppercase tracking-wide ${style.bg} ${style.text} ${style.border} ${sizeClasses} ${className}`}
      title={`Review state: ${style.label}`}
    >
      {style.label}
    </span>
  );
}

export { _BADGE_STYLES as REVIEW_BADGE_STYLES };
