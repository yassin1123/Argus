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

export interface MemoRendererProps {
  /** The writer's structured payload — any WriterReportBase subclass dump. */
  payload: Record<string, JsonValue>;
  /** The consulting mode the engagement ran under. Drives dispatch. */
  modeName: string;
  /** When supplied, each deepenable section gets a hover-state
   * "Deepen" affordance that calls ``onDeepen(path)``. */
  deepening?: DeepeningHook;
}

/** Wrap a rendered section in :class:`SectionWrapper` iff the host
 * supplied a deepening hook AND the section path is deepenable
 * (``isDeepenable`` excludes the recommendation per W9/D2 hard rule).
 */
function maybeWrap(
  sectionPath: string,
  deepening: DeepeningHook | undefined,
  content: JSX.Element | null,
): JSX.Element | null {
  if (!content) return content;
  if (!deepening || !isDeepenable(sectionPath)) return content;
  return (
    <SectionWrapper
      sectionPath={sectionPath}
      inFlight={deepening.inFlight}
      onDeepen={deepening.onDeepen}
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

export default function MemoRenderer({ payload, modeName, deepening }: MemoRendererProps) {
  const isMandA = modeName === "m_and_a_diligence";
  const ordered = orderedKeys(payload, modeName);

  return (
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
            {maybeWrap(k, deepening, (
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
            ? maybeWrap("synergy_estimate", deepening, (
                <SynergyBreakdown data={payload.synergy_estimate as never} />
              ))
            : null}
          {payload.valuation_range && typeof payload.valuation_range === "object" && !Array.isArray(payload.valuation_range)
            ? maybeWrap("valuation_range", deepening, (
                <ValuationRangeTable data={payload.valuation_range as never} />
              ))
            : null}
          {payload.integration_plan && typeof payload.integration_plan === "object" && !Array.isArray(payload.integration_plan)
            ? maybeWrap("integration_plan", deepening, (
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
}

export { default as SchemaDrivenSection } from "./SchemaDrivenSection";
export { default as ValuationRangeTable } from "./M_and_A/ValuationRangeTable";
export { default as SynergyBreakdown } from "./M_and_A/SynergyBreakdown";
export { default as IntegrationTimeline } from "./M_and_A/IntegrationTimeline";
