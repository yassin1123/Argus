"use client";

/**
 * SectionWrapper — Phase 2 / Week 9 / Day 2 + Phase 4 / Week 16 / Day 3.
 *
 * Wraps one rendered memo section. Two top-right affordances:
 *
 *   - Deepen (W9/D2) — opens the deepening composer for the section.
 *   - Comment (W16/D3) — opens the comment thread panel scoped to
 *     the section. Renders an unresolved-count badge when there are
 *     open threads, a quieter total-count badge when only resolved
 *     threads remain, and an icon-only hover affordance when the
 *     section has no comments yet.
 *
 * Hard rule from W9 spec: the recommendation never gets a Deepen
 * affordance. The :func:`isDeepenable` check in the host
 * orchestrator decides whether to render this wrapper at all
 * for a given section — here we just trust the path and render
 * the affordance.
 *
 * Comment affordance visibility (W16/D3 hard rule): hidden for
 * non-members. The host passes ``canComment=false`` for read-only
 * viewers and the affordance disappears entirely.
 */

import { ReactNode, useState } from "react";

import SectionCommentAffordance from "../Comments/SectionCommentAffordance";
import SectionOwnershipOverlay from "../Collaboration/SectionOwnershipOverlay";
import type { SectionStatus } from "@/lib/api/collaboration";

export interface SectionWrapperProps {
  sectionPath: string;
  /** Whether deepening is currently in-flight on this session. When
   * true the affordance is rendered disabled — one deepening at a
   * time, per W9/D2 hard rule. */
  inFlight: boolean;
  onDeepen: (sectionPath: string) => void;
  /** Optional comment surface — when omitted, no comment affordance
   * is rendered (used by tests / standalone deepening previews). */
  comments?: {
    unresolvedCount: number;
    totalCount: number;
    canComment: boolean;
    onOpen: (sectionPath: string) => void;
  };
  /** W17/D4 ownership surface — owner avatar + status badge. */
  ownership?: {
    owner: { user_id: string; full_name?: string; email?: string } | null;
    status: SectionStatus;
    canManage: boolean;
    canChangeStatus: boolean;
    memberOptions: Array<{ user_id: string; full_name?: string; email?: string }>;
    onAssign: (sectionPath: string, userId: string) => void | Promise<void>;
    onChangeStatus: (sectionPath: string, status: SectionStatus) => void | Promise<void>;
    onUnassign?: (sectionPath: string) => void | Promise<void>;
  };
  children: ReactNode;
}

export default function SectionWrapper({
  sectionPath,
  inFlight,
  onDeepen,
  comments,
  ownership,
  children,
}: SectionWrapperProps) {
  const [hovering, setHovering] = useState(false);
  const hasComments =
    !!comments && (comments.unresolvedCount > 0 || comments.totalCount > 0);
  // Persist the affordance when the section has any threads so the
  // historical context stays discoverable. Otherwise it's hover-only.
  const showCommentAffordance =
    !!comments && (hovering || hasComments);

  return (
    <div
      data-testid={`section-wrapper-${sectionPath}`}
      data-section-path={sectionPath}
      className="relative"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      {children}
      <div className="absolute right-2 top-2 flex items-center gap-2">
        {/* W17/D4 ownership overlay sits LEFT of the comment
            affordance — owner + status are the smaller, lower-
            priority signal; the comment affordance dominates when
            unresolved threads exist. */}
        {ownership && (
          <SectionOwnershipOverlay
            sectionPath={sectionPath}
            owner={ownership.owner}
            status={ownership.status}
            canManage={ownership.canManage}
            canChangeStatus={ownership.canChangeStatus}
            memberOptions={ownership.memberOptions}
            onAssign={ownership.onAssign}
            onChangeStatus={ownership.onChangeStatus}
            onUnassign={ownership.onUnassign}
          />
        )}
        {showCommentAffordance && comments && (
          <SectionCommentAffordance
            sectionPath={sectionPath}
            unresolvedCount={comments.unresolvedCount}
            totalCount={comments.totalCount}
            visible={comments.canComment || hasComments}
            onClick={() => comments.onOpen(sectionPath)}
          />
        )}
        {hovering ? (
          <button
            type="button"
            data-testid={`deepen-affordance-${sectionPath}`}
            onClick={() => !inFlight && onDeepen(sectionPath)}
            disabled={inFlight}
            title={
              inFlight
                ? "Another deepening is in progress on this engagement. Wait for it to finish."
                : `Deepen ${sectionPath}`
            }
            className="rounded border border-argus-firm-border bg-argus-firm-bg px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-argus-firm hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {inFlight ? "Deepening…" : "Deepen"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
