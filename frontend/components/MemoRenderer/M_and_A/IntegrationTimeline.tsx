"use client";

/**
 * Integration timeline — three bands (Day 1 / first 100 days /
 * first year). Workstreams render as lanes; each entry shows
 * owner role + milestone + dependencies.
 */

interface InitiativeBlock {
  workstream?: string;
  owner_role?: string;
  milestone?: string;
  dependencies?: string[];
}

export interface IntegrationTimelineProps {
  data: {
    day_one_priorities?: string[];
    first_100_days?: InitiativeBlock[];
    first_year?: InitiativeBlock[];
    integration_complexity_rating?: "low" | "medium" | "high" | string;
    complexity_rationale?: string;
  };
}

const COMPLEXITY_TONE: Record<string, string> = {
  low: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  medium: "border-argus-border-subtle bg-elevated text-argus-secondary",
  high: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

function InitiativeCard({ b }: { b: InitiativeBlock }) {
  return (
    <li className="rounded-sm border border-argus-border-subtle bg-surface p-2 text-[12px]">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="font-medium text-argus-primary">{b.workstream || "—"}</span>
        <span className="font-mono text-[10px] uppercase tracking-wide text-argus-tertiary">
          {b.owner_role || "—"}
        </span>
      </div>
      <p className="text-argus-secondary">{b.milestone || "—"}</p>
      {b.dependencies && b.dependencies.length > 0 ? (
        <ul className="mt-1 flex flex-wrap gap-1">
          {b.dependencies.map((d, i) => (
            <li
              key={i}
              className="rounded-sm border border-argus-border-subtle bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-argus-tertiary"
            >
              ↳ {d}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export default function IntegrationTimeline({ data }: IntegrationTimelineProps) {
  const day1 = data.day_one_priorities || [];
  const wk100 = data.first_100_days || [];
  const yr1 = data.first_year || [];
  const rating = data.integration_complexity_rating || "";
  return (
    <section className="mb-6" data-testid="integration-timeline">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="font-serif text-[18px] font-semibold text-argus-primary">
          Integration plan
        </h3>
        {rating ? (
          <span
            className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
              COMPLEXITY_TONE[rating] ||
              "border-argus-border-subtle bg-elevated text-argus-tertiary"
            }`}
            data-testid="integration-complexity"
          >
            {rating} complexity
          </span>
        ) : null}
      </div>
      {data.complexity_rationale ? (
        <p className="mb-3 text-[12px] italic text-argus-secondary">
          {data.complexity_rationale}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div data-testid="band-day-one">
          <span className="argus-label">Day 1</span>
          {day1.length === 0 ? (
            <p className="text-[11px] italic text-argus-tertiary">No priorities listed.</p>
          ) : (
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[12px] text-argus-primary">
              {day1.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
        </div>
        <div data-testid="band-100-days">
          <span className="argus-label">First 100 days</span>
          {wk100.length === 0 ? (
            <p className="text-[11px] italic text-argus-tertiary">No initiatives listed.</p>
          ) : (
            <ul className="mt-1 space-y-2">
              {wk100.map((b, i) => (
                <InitiativeCard key={i} b={b} />
              ))}
            </ul>
          )}
        </div>
        <div data-testid="band-first-year">
          <span className="argus-label">First year</span>
          {yr1.length === 0 ? (
            <p className="text-[11px] italic text-argus-tertiary">No initiatives listed.</p>
          ) : (
            <ul className="mt-1 space-y-2">
              {yr1.map((b, i) => (
                <InitiativeCard key={i} b={b} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
