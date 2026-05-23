"use client";

import { artifactAnchor, useComments } from "./CommentsController";

interface Props {
  artifactId: string;
  /** Display label for the panel header (e.g. "Deck: Kestrel"). */
  label?: string;
  /** Optional unresolved count if the host already knows it. */
  unresolvedCount?: number;
  /** Hide for non-members per W16/D3 hard rule. */
  visible?: boolean;
}

/**
 * Inline 💬 affordance for artifact cards.
 *
 * Comments anchor at artifact level — no deck-slide or
 * Excel-cell-level commenting in v1 per W16/D4 hard rule. Clicking
 * opens the :class:`ThreadPanel` scoped to ``artifact:<id>``.
 *
 * Defensive: when rendered outside the :class:`CommentsController`
 * (preview tools, isolated tests) the component renders nothing
 * rather than crashing the host.
 */
export default function ArtifactCommentAffordance({
  artifactId,
  label,
  unresolvedCount = 0,
  visible = true,
}: Props) {
  let ctx;
  try {
    ctx = useComments();
  } catch {
    return null;
  }
  if (!visible) return null;

  const anchor = artifactAnchor(artifactId);
  if (label) anchor.label = label;

  return (
    <button
      type="button"
      onClick={() => ctx!.openThread(anchor)}
      data-testid={`artifact-comment-${artifactId}`}
      title={
        unresolvedCount > 0
          ? `Open comments (${unresolvedCount} unresolved)`
          : `Comment on this artifact`
      }
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        padding: "0 4px",
        background: unresolvedCount > 0 ? "#fef3c7" : "transparent",
        border: 0,
        borderRadius: 4,
        color: unresolvedCount > 0 ? "#92400e" : "#6b7280",
        cursor: "pointer",
        fontSize: 11,
      }}
    >
      💬
      {unresolvedCount > 0 && (
        <span
          data-testid={`artifact-comment-badge-${artifactId}`}
          style={{ fontWeight: 600 }}
        >
          {unresolvedCount}
        </span>
      )}
    </button>
  );
}
