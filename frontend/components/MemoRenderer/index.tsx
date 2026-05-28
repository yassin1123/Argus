"use client";

/**
 * MemoRenderer — schema-driven dispatcher for the writer's
 * structured payload. Phase 2 / Week 7 / Day 3.
 *
 *   if mode_name === "m_and_a_diligence":
 *     -> ValuationRangeTable for valuation_range
 *     -> SynergyBreakdown for synergy_estimate
 *     -> IntegrationTimeline for integration_plan
 *     -> SchemaDrivenSection for everything else (target_overview,
 *        financial_profile, risks_and_mitigations,
 *        deal_structure_implications + the inherited base fields)
 *   otherwise:
 *     -> SchemaDrivenSection for everything
 *
 * Naming note: spec called this `MemoEditor/` but
 * `frontend/components/workspace/MemoEditor.tsx` is already taken
 * (a Tiptap-based artifact text editor — different concern).
 * Renamed to `MemoRenderer/` to avoid the collision.
 */

import { isDeepenable } from "@/lib/api/sectionDeepening";
import SectionWrapper from "@/components/SectionDeepening/SectionWrapper";
import { PilotFeedbackProvider } from "@/components/PilotFeedback/PilotFeedbackContext";

import FrameworksSection, { type FrameworksData } from "./Frameworks";
import IntegrationTimeline from "./M_and_A/IntegrationTimeline";
import SynergyBreakdown from "./M_and_A/SynergyBreakdown";
import ValuationRangeTable from "./M_and_A/ValuationRangeTable";
import SchemaDrivenSection, { type JsonValue } from "./SchemaDrivenSection";

/** W9/D2: the orchestrator's deepen hook, threaded into each
 * renderable section's :class:`SectionWrapper`. Optional — when
 * absent the memo renders without the deepen affordance, preserving
 * pre-W9 behaviour. */
export interface DeepeningHook {
  inFlight: boolean;
  onDeepen: (sectionPath: string) => void;
}

/** W16/D3: section-level comment hook. ``unresolvedBySection`` +
 * ``totalBySection`` drive the badge; ``onOpen`` opens the comment
 * thread panel; ``canComment`` hides the affordance for non-members.
 * Optional — when absent the memo renders without the comment
 * affordance (used by previews / tests). */
export interface CommentsHook {
  unresolvedBySection: Record<string, number>;
  totalBySection: Record<string, number>;
  canComment: boolean;
  onOpen: (sectionPath: string) => void;
}

/** W17/D4: section-ownership hook. Optional — when absent the memo
 * renders without owner avatar / status badge. Mirrors the comments
 * hook shape so MemoRenderer threads it through identically. */
export interface OwnershipHook {
  /** section_path → assignment row (or null when unassigned). */
  bySection: Record<string, {
    user_id: string | null;
    status: import("@/lib/api/collaboration").SectionStatus;
  }>;
  /** Engagement members for the assign-owner picker. */
  memberOptions: Array<{ user_id: string; full_name?: string; email?: string }>;
  /** Whether the current user can re-assign owners (lead/admin). */
  canManage: boolean;
  /** Per-section: can the current user change status? Owner/lead/admin. */
  canChangeStatusFor: (sectionPath: string) => boolean;
  onAssign: (sectionPath: string, userId: string) => void | Promise<void>;
  onChangeStatus: (
    sectionPath: string,
    status: import("@/lib/api/collaboration").SectionStatus,
  ) => void | Promise<void>;
  onUnassign?: (sectionPath: string) => void | Promise<void>;
}

export interface MemoRendererProps {
  /** The writer's structured payload — any WriterReportBase subclass dump. */
  payload: Record<string, JsonValue>;
  /** The consulting mode the engagement ran under. Drives dispatch. */
  modeName: string;
  /** When supplied, each deepenable section gets a hover-state
   * "Deepen" affordance that calls ``onDeepen(path)``. */
  deepening?: DeepeningHook;
  /** W16/D3: when supplied, each section gets a comment affordance +
   * unresolved badge wired to the host's comments controller. */
  comments?: CommentsHook;
  /** W17/D4: when supplied, each section gets an owner avatar +
   * status badge in the top-right corner. */
  ownership?: OwnershipHook;
  /** W24/D3: when supplied, each claim gets a one-click
   * "is this verified correctly?" feedback affordance scoped to this
   * session. Absent → the affordance hides. */
  sessionId?: string;
}

/** Wrap a rendered section in :class:`SectionWrapper` iff the host
 * supplied a deepening OR comments hook AND the section path is
 * eligible (``isDeepenable`` excludes the recommendation per W9/D2
 * hard rule; the comment affordance has no such carve-out — every
 * section can be commented on).
 */
function maybeWrap(
  sectionPath: string,
  deepening: DeepeningHook | undefined,
  comments: CommentsHook | undefined,
  ownership: OwnershipHook | undefined,
  content: JSX.Element | null,
): JSX.Element | null {
  if (!content) return content;
  const hasDeepen = !!deepening && isDeepenable(sectionPath);
  const hasComments = !!comments;
  const hasOwnership = !!ownership;
  if (!hasDeepen && !hasComments && !hasOwnership) return content;
  const commentsProp = comments
    ? {
        unresolvedCount: comments.unresolvedBySection[sectionPath] ?? 0,
        totalCount: comments.totalBySection[sectionPath] ?? 0,
        canComment: comments.canComment,
        onOpen: comments.onOpen,
      }
    : undefined;
  const ownershipProp = ownership
    ? (() => {
        const assignment = ownership.bySection[sectionPath];
        const ownerId = assignment?.user_id ?? null;
        const ownerOption = ownerId
          ? ownership.memberOptions.find((m) => m.user_id === ownerId)
          : null;
        return {
          owner: ownerId
            ? {
                user_id: ownerId,
                full_name: ownerOption?.full_name,
                email: ownerOption?.email,
              }
            : null,
          status: assignment?.status ?? ("not_started" as const),
          canManage: ownership.canManage,
          canChangeStatus: ownership.canChangeStatusFor(sectionPath),
          memberOptions: ownership.memberOptions,
          onAssign: ownership.onAssign,
          onChangeStatus: ownership.onChangeStatus,
          onUnassign: ownership.onUnassign,
        };
      })()
    : undefined;
  return (
    <SectionWrapper
      sectionPath={sectionPath}
      inFlight={hasDeepen ? deepening!.inFlight : false}
      onDeepen={hasDeepen ? deepening!.onDeepen : () => {}}
      comments={commentsProp}
      ownership={ownershipProp}
    >
      {content}
    </SectionWrapper>
  );
}

const M_AND_A_RENDERED_KEYS = new Set([
  "valuation_range",
  "synergy_estimate",
  "integration_plan",
]);

// Fields we never render at top level (already covered elsewhere or
// internal). Keep this list tight — most of the base payload's
// "consulting_payload" subfields ARE useful in the memo and stay in
// the schema-driven walk.
const SKIP_KEYS = new Set([
  "mode",                        // displayed in header, not body
  "metadata",                    // internal forward-compat bag
  "frameworks",                  // W8/D3: dispatched to FrameworksSection
]);

const ORDERED_BASE_KEYS = [
  "recommendation",
  "confidence_level",
  "summary",
  "key_reasons",
  "risks",
  "counterarguments",
  "next_steps",
  "decision_criteria",
  "options_matrix",
  "kill_criteria",
  "what_would_change_our_mind",
  "evidence_ledger_summary",
  "sources",
  "caveats",
  "executive_insights",
  "key_risks_structured",
  "recommendation_claim_ids",
];

const ORDERED_M_AND_A_KEYS = [
  "target_overview",
  "financial_profile",
  // synergy_estimate / valuation_range / integration_plan are dispatched
  // to bespoke renderers and rendered between target_overview and the
  // remaining base fields below.
  "risks_and_mitigations",
  "deal_structure_implications",
];

function orderedKeys(payload: Record<string, JsonValue>, modeName: string): string[] {
  const known: string[] = [];
  if (modeName === "m_and_a_diligence") {
    for (const k of ORDERED_M_AND_A_KEYS) if (k in payload) known.push(k);
  }
  for (const k of ORDERED_BASE_KEYS) if (k in payload) known.push(k);
  // Anything not explicitly ordered, in original insertion order.
  for (const k of Object.keys(payload)) {
    if (known.includes(k)) continue;
    if (SKIP_KEYS.has(k)) continue;
    if (modeName === "m_and_a_diligence" && M_AND_A_RENDERED_KEYS.has(k)) continue;
    known.push(k);
  }
  return known;
}

export default function MemoRenderer({
  payload,
  modeName,
  deepening,
  comments,
  ownership,
  sessionId,
}: MemoRendererProps) {
  const isMandA = modeName === "m_and_a_diligence";
  const ordered = orderedKeys(payload, modeName);

  const body = (
    <div data-testid="memo-renderer" data-mode={modeName} className="mx-auto max-w-[900px] px-4 py-6">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="font-serif text-[24px] font-semibold text-argus-primary">
          {typeof payload.recommendation === "string" && payload.recommendation
            ? payload.recommendation
            : "Engagement memo"}
        </h2>
        <span className="font-mono text-[10px] uppercase tracking-wide text-argus-tertiary">
          {modeName}
        </span>
      </header>

      {/* Structured-payload base fields, in canonical order. Each
          section gets a hover-state Deepen affordance when the host
          supplied a deepening hook (W9/D2). */}
      {ordered.map((k) => {
        const v = payload[k];
        if (v === undefined) return null;
        return (
          <div key={`gen-${k}`}>
            {maybeWrap(k, deepening, comments, ownership, (
              <SchemaDrivenSection title={k} value={v} />
            ))}
          </div>
        );
      })}

      {/* M&A-specific renderers. Inserted after the base section block
          so the recommendation + summary lead the memo, then the
          structured deal sections follow. */}
      {isMandA ? (
        <>
          {payload.synergy_estimate && typeof payload.synergy_estimate === "object" && !Array.isArray(payload.synergy_estimate)
            ? maybeWrap("synergy_estimate", deepening, comments, ownership, (
                <SynergyBreakdown data={payload.synergy_estimate as never} />
              ))
            : null}
          {payload.valuation_range && typeof payload.valuation_range === "object" && !Array.isArray(payload.valuation_range)
            ? maybeWrap("valuation_range", deepening, comments, ownership, (
                <ValuationRangeTable data={payload.valuation_range as never} />
              ))
            : null}
          {payload.integration_plan && typeof payload.integration_plan === "object" && !Array.isArray(payload.integration_plan)
            ? maybeWrap("integration_plan", deepening, comments, ownership, (
                <IntegrationTimeline data={payload.integration_plan as never} />
              ))
            : null}
        </>
      ) : null}

      {/* W8/D3: optional structured frameworks (2x2, Porter's Five
          Forces, Value Chain). Mode-agnostic — any memo can carry one,
          two, all three, or none. FrameworksSection is a no-op when
          payload.frameworks is null or all slots are null, so
          backward compat is preserved.

          W9/D2: frameworks now accept a deepening hook too. The
          FrameworksSection wraps each non-null framework in its own
          SectionWrapper internally — same affordance pattern as
          the base sections. */}
      <FrameworksSection
        data={(payload.frameworks ?? null) as FrameworksData | null}
        deepening={deepening}
      />
    </div>
  );

  // W24/D3: when a sessionId is supplied, provide it to the per-claim
  // verification-feedback affordances nested in the rendered sections.
  return sessionId ? (
    <PilotFeedbackProvider sessionId={sessionId}>{body}</PilotFeedbackProvider>
  ) : (
    body
  );
}

export { default as SchemaDrivenSection } from "./SchemaDrivenSection";
export { default as ValuationRangeTable } from "./M_and_A/ValuationRangeTable";
export { default as SynergyBreakdown } from "./M_and_A/SynergyBreakdown";
export { default as IntegrationTimeline } from "./M_and_A/IntegrationTimeline";
