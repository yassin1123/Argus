"use client";

interface Props {
  sectionPath: string;
  /** Unresolved comment count for this section. 0 hides the badge
   *  but keeps the icon (icon is the affordance for the first
   *  comment); the parent decides whether to hide the whole thing
   *  for non-members via the ``visible`` prop. */
  unresolvedCount: number;
  /** Total comments anchored to this section (resolved + open).
   *  Used so the icon stays persistent after the last unresolved
   *  thread is closed — the section still has historical context. */
  totalCount: number;
  /** Hide for non-members per W16/D3 hard rule. */
  visible: boolean;
  onClick: () => void;
}

/**
 * Floating "comment" affordance attached to a memo section.
 *
 * Icon-only on hover when there are no comments; icon + badge when
 * there are unresolved threads; smaller, ghosted icon when the
 * section has only resolved threads (still useful to find the
 * historical context, less visual weight).
 *
 * The parent (SectionWrapper) decides positioning. This component
 * just renders the button + its badge.
 */
export default function SectionCommentAffordance({
  sectionPath,
  unresolvedCount,
  totalCount,
  visible,
  onClick,
}: Props) {
  if (!visible) return null;

  const hasUnresolved = unresolvedCount > 0;
  const hasAny = totalCount > 0;
  // If there are no comments at all, render a hover-only button.
  // CSS-wise we still mount it; the parent can apply opacity-on-
  // hover via className. Keeping the structure simple — no CSS
  // module overhead.
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={`section-comment-affordance-${sectionPath}`}
      data-has-unresolved={hasUnresolved ? "true" : "false"}
      aria-label={
        hasUnresolved
          ? `Open comments for ${sectionPath} (${unresolvedCount} unresolved)`
          : `Comment on ${sectionPath}`
      }
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 6px",
        background: hasUnresolved ? "#fef3c7" : hasAny ? "#f3f4f6" : "transparent",
        border: hasUnresolved
          ? "1px solid #fcd34d"
          : hasAny
            ? "1px solid #e5e7eb"
            : "1px dashed transparent",
        borderRadius: 6,
        fontSize: 12,
        cursor: "pointer",
        color: hasUnresolved ? "#92400e" : "#374151",
      }}
    >
      <span aria-hidden>💬</span>
      {hasAny && (
        <span
          data-testid={`section-comment-badge-${sectionPath}`}
          style={{ fontWeight: 600 }}
        >
          {unresolvedCount > 0 ? unresolvedCount : totalCount}
        </span>
      )}
    </button>
  );
}
