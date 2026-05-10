"use client";

/**
 * Synergy breakdown — three piles (revenue / cost / dis-) with
 * NPV total at the bottom. Each synergy line shows magnitude,
 * timing, confidence chip, and basis citations.
 */

interface Synergy {
  type?: string;
  magnitude_gbp_m?: number;
  timing_months?: number;
  confidence?: "high" | "medium" | "low" | string;
  basis_citations?: string[];
}

export interface SynergyBreakdownProps {
  data: {
    revenue_synergies?: Synergy[];
    cost_synergies?: Synergy[];
    dis_synergies?: Synergy[];
    net_present_value?: {
      low_gbp_m?: number;
      base_gbp_m?: number;
      high_gbp_m?: number;
      discount_rate_pct?: number;
    };
    realization_timeline?: string;
  };
}

const PILE_TONE: Record<"revenue" | "cost" | "dis", string> = {
  revenue: "border-argus-firm-border bg-argus-firm-bg",
  cost: "border-argus-accent-border bg-argus-accent-bg",
  dis: "border-argus-contested-border bg-argus-contested-bg",
};

const CONFIDENCE_TONE: Record<string, string> = {
  high: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  medium: "border-argus-border-subtle bg-elevated text-argus-secondary",
  low: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

function formatGbp(m?: number): string {
  if (typeof m !== "number" || !Number.isFinite(m)) return "—";
  const sign = m < 0 ? "-" : "";
  return `${sign}£${Math.abs(m).toLocaleString(undefined, { maximumFractionDigits: 1 })}m`;
}

function SynergyPile({
  label,
  tone,
  rows,
  showSign,
}: {
  label: string;
  tone: "revenue" | "cost" | "dis";
  rows: Synergy[];
  showSign?: "+" | "-";
}) {
  const total = rows.reduce(
    (acc, r) => acc + (typeof r.magnitude_gbp_m === "number" ? r.magnitude_gbp_m : 0),
    0,
  );
  return (
    <div
      className={`rounded-argus-sm border p-3 ${PILE_TONE[tone]}`}
      data-testid={`synergy-pile-${tone}`}
    >
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="font-serif text-[14px] font-semibold text-argus-primary">{label}</h4>
        <span className="font-mono text-[12px] tabular-nums text-argus-primary">
          {showSign === "-" ? "-" : showSign === "+" ? "+" : ""}
          {formatGbp(total)}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="text-[11px] italic text-argus-tertiary">No items.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((s, i) => (
            <li
              key={i}
              className="rounded-sm border border-argus-border-subtle bg-surface p-2 text-[12px]"
            >
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="font-medium text-argus-primary">{s.type || "—"}</span>
                <span className="font-mono tabular-nums text-argus-primary">
                  {formatGbp(s.magnitude_gbp_m)}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[10px] text-argus-tertiary">
                {typeof s.timing_months === "number" ? (
                  <span className="font-mono">{s.timing_months}m timing</span>
                ) : null}
                {s.confidence ? (
                  <span
                    className={`rounded-sm border px-1.5 py-0.5 uppercase tracking-wide ${
                      CONFIDENCE_TONE[s.confidence] ||
                      "border-argus-border-subtle bg-elevated text-argus-tertiary"
                    }`}
                  >
                    {s.confidence}
                  </span>
                ) : null}
              </div>
              {s.basis_citations && s.basis_citations.length > 0 ? (
                <ul className="mt-1 list-disc pl-4 text-[10px] text-argus-secondary">
                  {s.basis_citations.map((b, j) => (
                    <li key={j}>{b}</li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SynergyBreakdown({ data }: SynergyBreakdownProps) {
  const npv = data.net_present_value || {};
  return (
    <section className="mb-6" data-testid="synergy-breakdown">
      <h3 className="mb-2 font-serif text-[18px] font-semibold text-argus-primary">
        Synergy estimate
      </h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <SynergyPile label="Revenue" tone="revenue" rows={data.revenue_synergies || []} showSign="+" />
        <SynergyPile label="Cost" tone="cost" rows={data.cost_synergies || []} showSign="+" />
        <SynergyPile label="Dis-synergies" tone="dis" rows={data.dis_synergies || []} showSign="-" />
      </div>

      <div
        className="mt-3 grid grid-cols-1 gap-2 rounded-argus-sm border border-argus-border-subtle bg-elevated p-3 sm:grid-cols-4"
        data-testid="synergy-npv"
      >
        <div>
          <span className="argus-label">NPV (low)</span>
          <p className="font-mono text-[13px] tabular-nums text-argus-primary">
            {formatGbp(npv.low_gbp_m)}
          </p>
        </div>
        <div>
          <span className="argus-label">NPV (base)</span>
          <p className="font-mono text-[13px] tabular-nums text-argus-primary">
            {formatGbp(npv.base_gbp_m)}
          </p>
        </div>
        <div>
          <span className="argus-label">NPV (high)</span>
          <p className="font-mono text-[13px] tabular-nums text-argus-primary">
            {formatGbp(npv.high_gbp_m)}
          </p>
        </div>
        <div>
          <span className="argus-label">Discount rate</span>
          <p className="font-mono text-[13px] tabular-nums text-argus-primary">
            {typeof npv.discount_rate_pct === "number"
              ? `${npv.discount_rate_pct.toFixed(1)}%`
              : "—"}
          </p>
        </div>
      </div>

      {data.realization_timeline ? (
        <p className="mt-2 text-[12px] italic text-argus-secondary">
          Realisation: {data.realization_timeline}
        </p>
      ) : null}
    </section>
  );
}
