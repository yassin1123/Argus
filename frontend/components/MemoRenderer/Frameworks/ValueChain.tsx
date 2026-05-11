"use client";

/**
 * Value Chain renderer — W8/D3.
 *
 * Two-row layout per Porter convention: primary activities on top
 * (inbound logistics → operations → outbound logistics → marketing
 * and sales → service), support activities on bottom (firm
 * infrastructure, hr management, technology development,
 * procurement).
 *
 * Each activity is a card showing name + assessment +
 * competitive_implication + evidence citations.
 *
 * Functional, not fancy — W8/D3 hard rule. No fancy arrow geometry,
 * no SVG overlays. Phase 3 polish handles arrows + value-margin
 * triangle along the right edge.
 */

export type ActivityCategory = "primary" | "support";

export type CanonicalStep =
  | "inbound_logistics"
  | "operations"
  | "outbound_logistics"
  | "marketing_and_sales"
  | "service"
  | "firm_infrastructure"
  | "hr_management"
  | "technology_development"
  | "procurement";

export interface ValueChainActivityData {
  name: string;
  category: ActivityCategory;
  canonical_step: CanonicalStep;
  assessment: string;
  competitive_implication: string;
  evidence_citations: string[];
}

export interface ValueChainData {
  business_context: string;
  activities: ValueChainActivityData[];
  overall_thesis: string;
}

export interface ValueChainProps {
  data: ValueChainData;
}

// Canonical row ordering — primary activities follow Porter's
// left-to-right flow; support activities are ordered top-down in
// the original framework but we lay them out left-to-right for
// horizontal rendering parity with the primary row.
const PRIMARY_ORDER: CanonicalStep[] = [
  "inbound_logistics",
  "operations",
  "outbound_logistics",
  "marketing_and_sales",
  "service",
];

const SUPPORT_ORDER: CanonicalStep[] = [
  "firm_infrastructure",
  "hr_management",
  "technology_development",
  "procurement",
];

function ActivityCard({ activity }: { activity: ValueChainActivityData }) {
  return (
    <article
      data-testid={`value-chain-activity-${activity.canonical_step}`}
      data-category={activity.category}
      className="flex-1 min-w-[180px] rounded-md border border-argus-border-subtle bg-surface p-3"
    >
      <header className="mb-1 flex items-baseline justify-between">
        <h4 className="font-serif text-[13px] font-semibold text-argus-primary">{activity.name}</h4>
        <span className="font-mono text-[9px] uppercase tracking-wide text-argus-tertiary">
          {activity.canonical_step.replace(/_/g, " ")}
        </span>
      </header>
      <p className="text-[12px] leading-relaxed text-argus-secondary" data-testid="activity-assessment">
        {activity.assessment}
      </p>
      <p
        className="mt-1 text-[11px] italic leading-snug text-argus-tertiary"
        data-testid="activity-implication"
      >
        {activity.competitive_implication}
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {activity.evidence_citations.map((cid, i) => (
          <span
            key={`${activity.canonical_step}-cite-${i}`}
            className="rounded border border-argus-border-subtle bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-argus-tertiary"
          >
            {cid}
          </span>
        ))}
      </div>
    </article>
  );
}

function ActivityRow({
  label,
  category,
  activities,
  order,
}: {
  label: string;
  category: ActivityCategory;
  activities: ValueChainActivityData[];
  order: CanonicalStep[];
}) {
  // Sort activities for this category by canonical_step's position
  // in the canonical order; unknown steps fall to the end.
  const filtered = activities.filter((a) => a.category === category);
  const sorted = [...filtered].sort((a, b) => {
    const ai = order.indexOf(a.canonical_step);
    const bi = order.indexOf(b.canonical_step);
    const aRank = ai === -1 ? Number.MAX_SAFE_INTEGER : ai;
    const bRank = bi === -1 ? Number.MAX_SAFE_INTEGER : bi;
    return aRank - bRank;
  });
  return (
    <div data-testid={`value-chain-row-${category}`} className="space-y-1">
      <h4 className="text-[10px] uppercase tracking-wide text-argus-tertiary">{label}</h4>
      <div className="flex flex-wrap gap-2">
        {sorted.length === 0 ? (
          <span className="text-[11px] italic text-argus-tertiary">
            No {category} activities populated.
          </span>
        ) : (
          sorted.map((activity, i) => (
            <ActivityCard key={`${category}-${i}-${activity.canonical_step}`} activity={activity} />
          ))
        )}
      </div>
    </div>
  );
}

export default function ValueChain({ data }: ValueChainProps) {
  return (
    <section
      data-testid="value-chain"
      className="rounded-md border border-argus-border-subtle bg-surface p-4"
    >
      <header className="mb-3">
        <h3 className="font-serif text-[16px] font-semibold text-argus-primary">Value Chain</h3>
        <p className="mt-1 text-[12px] text-argus-tertiary" data-testid="business-context">
          {data.business_context}
        </p>
      </header>

      <div className="space-y-3">
        <ActivityRow
          label="Primary activities"
          category="primary"
          activities={data.activities}
          order={PRIMARY_ORDER}
        />
        <ActivityRow
          label="Support activities"
          category="support"
          activities={data.activities}
          order={SUPPORT_ORDER}
        />
      </div>

      <p className="mt-3 text-[13px] leading-relaxed text-argus-secondary" data-testid="overall-thesis">
        {data.overall_thesis}
      </p>
    </section>
  );
}
