"use client";

/**
 * Porter's Five Forces renderer — W8/D3.
 *
 * Vertical-stack layout per the spec's "vertical is simpler — ship
 * that" guidance. Star/cross layout is Phase 3 polish.
 *
 * Five force cards, each with intensity badge (low/moderate/high
 * mapped to green/amber/red via existing design tokens), rationale,
 * key driver chips, and evidence citation links.
 *
 * Header carries the market_definition + overall_attractiveness
 * badge so a reader can scan the headline without parsing each
 * force.
 */

export type ForceIntensity = "low" | "moderate" | "high";

export interface ForceAssessmentData {
  intensity: ForceIntensity;
  rationale: string;
  key_drivers: string[];
  evidence_citations: string[];
}

export interface PortersFiveForcesData {
  market_definition: string;
  rivalry: ForceAssessmentData;
  supplier_power: ForceAssessmentData;
  buyer_power: ForceAssessmentData;
  substitute_threat: ForceAssessmentData;
  new_entrant_threat: ForceAssessmentData;
  overall_attractiveness: ForceIntensity;
  overall_rationale: string;
}

export interface PortersFiveForcesProps {
  data: PortersFiveForcesData;
}

// Intensity → semantic palette mapping. High force intensity = bad
// for industry attractiveness, so we map it to the contested (red)
// tone; low = good = firm (green); moderate = accent (amber).
const INTENSITY_TONE: Record<ForceIntensity, string> = {
  low: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  moderate: "border-argus-accent-border bg-argus-accent-bg text-argus-secondary",
  high: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

const FORCE_LABELS: Record<keyof Omit<PortersFiveForcesData, "market_definition" | "overall_attractiveness" | "overall_rationale">, string> = {
  rivalry: "Rivalry among existing competitors",
  supplier_power: "Bargaining power of suppliers",
  buyer_power: "Bargaining power of buyers",
  substitute_threat: "Threat of substitutes",
  new_entrant_threat: "Threat of new entrants",
};

const FORCE_ORDER: (keyof typeof FORCE_LABELS)[] = [
  "rivalry",
  "supplier_power",
  "buyer_power",
  "substitute_threat",
  "new_entrant_threat",
];

function IntensityBadge({ intensity }: { intensity: ForceIntensity }) {
  return (
    <span
      data-testid="intensity-badge"
      data-intensity={intensity}
      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${INTENSITY_TONE[intensity]}`}
    >
      {intensity}
    </span>
  );
}

function ForceCard({
  forceKey,
  label,
  force,
}: {
  forceKey: string;
  label: string;
  force: ForceAssessmentData;
}) {
  return (
    <article
      data-testid={`porters-force-${forceKey}`}
      className="rounded-md border border-argus-border-subtle bg-surface p-3"
    >
      <header className="mb-2 flex items-baseline justify-between gap-2">
        <h4 className="font-serif text-[14px] font-semibold text-argus-primary">{label}</h4>
        <IntensityBadge intensity={force.intensity} />
      </header>
      <p className="text-[12px] leading-relaxed text-argus-secondary">{force.rationale}</p>
      <div className="mt-2 flex flex-wrap gap-1" data-testid="key-drivers">
        {force.key_drivers.map((driver, i) => (
          <span
            key={`${forceKey}-driver-${i}`}
            className="rounded border border-argus-border-subtle bg-elevated px-2 py-0.5 text-[11px] text-argus-secondary"
          >
            {driver}
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {force.evidence_citations.map((cid, i) => (
          <span
            key={`${forceKey}-cite-${i}`}
            className="rounded border border-argus-border-subtle bg-surface px-1.5 py-0.5 font-mono text-[10px] text-argus-tertiary"
            data-testid="evidence-citation"
          >
            {cid}
          </span>
        ))}
      </div>
    </article>
  );
}

export default function PortersFiveForces({ data }: PortersFiveForcesProps) {
  return (
    <section
      data-testid="porters-five-forces"
      className="rounded-md border border-argus-border-subtle bg-surface p-4"
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-serif text-[16px] font-semibold text-argus-primary">Porter's Five Forces</h3>
          <p className="mt-1 text-[12px] text-argus-tertiary" data-testid="market-definition">
            {data.market_definition}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="text-[10px] uppercase tracking-wide text-argus-tertiary">Overall attractiveness</span>
          <IntensityBadge intensity={data.overall_attractiveness} />
        </div>
      </header>

      <div className="space-y-2">
        {FORCE_ORDER.map((key) => (
          <ForceCard key={key} forceKey={key} label={FORCE_LABELS[key]} force={data[key]} />
        ))}
      </div>

      <p className="mt-3 text-[13px] leading-relaxed text-argus-secondary" data-testid="overall-rationale">
        {data.overall_rationale}
      </p>
    </section>
  );
}
