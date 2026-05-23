"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  AnchorRef,
  AnchorType,
  CountsResponse,
  FirmMemberLite,
  getCounts,
} from "@/lib/api/comments";

import ThreadPanel, { ThreadPanelAnchor } from "./ThreadPanel";

export interface CommentsContextValue {
  /** Open the panel scoped to an anchor. */
  openThread: (anchor: ThreadPanelAnchor) => void;
  /** Section anchor → unresolved count, used by section affordances. */
  unresolvedBySection: Record<string, number>;
  /** Section anchor → total comments (resolved + open). */
  totalBySection: Record<string, number>;
  /** Whole-anchor-type counts, e.g. by_anchor_type.claim = 4. */
  byAnchorType: Record<string, number>;
  /** Refetch the count surface. Children fire this after an action. */
  refreshCounts: () => Promise<void>;
}

const CommentsContext = createContext<CommentsContextValue | null>(null);

export function useComments(): CommentsContextValue {
  const ctx = useContext(CommentsContext);
  if (!ctx) {
    throw new Error("useComments must be used inside CommentsController");
  }
  return ctx;
}

/**
 * Like :func:`useComments` but returns ``null`` instead of throwing
 * when the consumer is mounted outside :class:`CommentsController`.
 * Useful for affordances (claim / artifact buttons) that need to
 * render cleanly in standalone previews / tests where the controller
 * isn't wired up.
 */
export function useCommentsOptional(): CommentsContextValue | null {
  return useContext(CommentsContext);
}

interface Props {
  sessionId: string;
  currentUserId: string;
  firmMembers: FirmMemberLite[];
  canComment: boolean;
  lockedBanner?: string | null;
  children: ReactNode;
}

/**
 * Top-level wrapper for the W16/D3 comments surface.
 *
 * Owns:
 *   - The currently-open ThreadPanel (one panel at a time).
 *   - The per-section + per-anchor counts that drive the badges.
 *
 * Children read counts via :func:`useComments` and request to open
 * the panel for a specific anchor. The panel itself is a sibling so
 * the page layout stays untouched.
 *
 * Mounting strategy: drop this once in the workspace shell, between
 * the rail/sidebar and the MemoRenderer. Components anywhere inside
 * can call ``useComments().openThread(...)`` to drive it.
 */
export default function CommentsController({
  sessionId,
  currentUserId,
  firmMembers,
  canComment,
  lockedBanner = null,
  children,
}: Props) {
  const [anchor, setAnchor] = useState<ThreadPanelAnchor | null>(null);
  const [counts, setCounts] = useState<CountsResponse>({
    by_anchor_type: {},
    by_section_path: {},
    unresolved_total: 0,
    total: 0,
  });

  const refreshCounts = useCallback(async () => {
    try {
      const next = await getCounts(sessionId);
      setCounts(next);
    } catch {
      // Counts are advisory — don't blow up the page if the
      // endpoint is unavailable.
    }
  }, [sessionId]);

  useEffect(() => {
    void refreshCounts();
  }, [refreshCounts]);

  const value: CommentsContextValue = useMemo(
    () => ({
      openThread: (a) => setAnchor(a),
      unresolvedBySection: counts.by_section_path,
      // The counts endpoint returns by_section_path for ROOT counts; we
      // expose it as both "unresolved" + "total" since the API also
      // reports unresolved_total separately. The badge prefers
      // unresolved, falling back to total — that's the spec's
      // "persistent if the section has comments" rule.
      totalBySection: counts.by_section_path,
      byAnchorType: counts.by_anchor_type,
      refreshCounts,
    }),
    [counts, refreshCounts],
  );

  return (
    <CommentsContext.Provider value={value}>
      {children}
      <ThreadPanel
        sessionId={sessionId}
        anchor={anchor}
        currentUserId={currentUserId}
        firmMembers={firmMembers}
        canComment={canComment}
        lockedBanner={lockedBanner}
        onClose={() => setAnchor(null)}
        onMutated={refreshCounts}
      />
    </CommentsContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Convenience anchor builders so call sites don't repeat the shape.
// ---------------------------------------------------------------------------

export function sectionAnchor(sectionPath: string): ThreadPanelAnchor {
  return {
    anchor_type: "section",
    anchor_ref: { section_path: sectionPath },
    label: sectionPath,
  };
}

export function claimAnchor(claimId: string): ThreadPanelAnchor {
  return {
    anchor_type: "claim",
    anchor_ref: { claim_id: claimId },
    label: `claim: ${claimId}`,
  };
}

export function engagementAnchor(): ThreadPanelAnchor {
  return { anchor_type: "engagement", anchor_ref: {}, label: "engagement" };
}

export function artifactAnchor(artifactId: string): ThreadPanelAnchor {
  return {
    anchor_type: "artifact",
    anchor_ref: { artifact_id: artifactId },
    label: `artifact: ${artifactId.slice(0, 8)}`,
  };
}

export type { ThreadPanelAnchor } from "./ThreadPanel";
export { default as ThreadPanel } from "./ThreadPanel";
export { default as MentionInput } from "./MentionInput";
export { default as SectionCommentAffordance } from "./SectionCommentAffordance";
