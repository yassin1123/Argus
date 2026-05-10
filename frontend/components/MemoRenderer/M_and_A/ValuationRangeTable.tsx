"use client";

/**
 * Valuation range — 3-column comparison (low / base / high) with
 * methodology rows beneath each price. Optional comparable
 * transactions table at the bottom.
 *
 * Functional, not fancy (per W7/D3 hard rule "Don't make the
 * M&A-specific renderers fancy. Phase 3 handles polish.").
 */

import type { JsonValue } from "../SchemaDrivenSection";

interface ValuationPoint {
  gbp_m?: number;
  methodology?: string;
  key_assumptions?: string[];
}

export interface ValuationRangeTableProps {
  /** ValuationRange dict from MAndADiligenceReportPayload. */
  data: {
    low?: ValuationPoint;
    base?: ValuationPoint;
    high?: ValuationPoint;
    multiples_implied?: Record<string, number>;
    comparable_transactions_cited?: Array<{
      target?: string;
      acquirer?: string;
      year?: number;
      multiple?: string;
      source_citation?: string;
    }>;
  };
}

function formatGbp(m?: number): string {
  if (typeof m !== "number" || !Number.isFinite(m)) return "—";
  return `£${m.toLocaleString(undefined, { maximumFractionDigits: 1 })}m`;
}

const COLUMN_TONE: Record<"low" | "base" | "high", string> = {
  low: "border-argus-border-subtle bg-surface",
  base: "border-argus-firm-border bg-argus-firm-bg",
  high: "border-argus-border-subtle bg-surface",
};

function pointCell(label: "low" | "base" | "high", point?: ValuationPoint) {
  return (
    <td
      key={label}
      className={`align-top border-l border-argus-border-subtle px-3 py-2 ${COLUMN_TONE[label]}`}
      data-testid={`valuation-${label}-cell`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wide text-argus-tertiary">
          {label}
        </span>
        <span className="font-serif text-[18px] font-semibold tabular-nums text-argus-primary">
          {formatGbp(point?.gbp_m)}
        </span>
      </div>
      <p
        className="mt-2 text-[11px] leading-snug text-argus-primary"
        data-testid={`valuation-${label}-method`}
      >
        <span className="block font-mono uppercase tracking-wide text-[9px] text-argus-tertiary">
          methodology
        </span>
        {point?.methodology || "—"}
      </p>
      {point?.key_assumptions && point.key_assumptions.length > 0 ? (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[11px] text-argus-secondary">
          {point.key_assumptions.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      ) : null}
    </td>
  );
}

export default function ValuationRangeTable({ data }: ValuationRangeTableProps) {
  const cmps = data.comparable_transactions_cited || [];
  const multiples = data.multiples_implied || {};
  return (
    <section className="mb-6" data-testid="valuation-range-table">
      <h3 className="mb-2 font-serif text-[18px] font-semibold text-argus-primary">
        Valuation range
      </h3>
      <table className="w-full border-collapse rounded-argus-sm border border-argus-border-subtle">
        <tbody>
          <tr>
            {pointCell("low", data.low)}
            {pointCell("base", data.base)}
            {pointCell("high", data.high)}
          </tr>
        </tbody>
      </table>

      {Object.keys(multiples).length > 0 ? (
        <div className="mt-3" data-testid="multiples-implied">
          <span className="argus-label">Multiples implied (base case)</span>
          <ul className="mt-1 flex flex-wrap gap-2">
            {Object.entries(multiples).map(([k, v]) => (
              <li
                key={k}
                className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-0.5 font-mono text-[11px] text-argus-primary"
              >
                {k}: {Number(v).toFixed(2)}x
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {cmps.length > 0 ? (
        <div className="mt-3" data-testid="comparable-transactions">
          <span className="argus-label">Comparable transactions cited</span>
          <table className="mt-1 w-full text-[11px]">
            <thead>
              <tr className="border-b border-argus-border-subtle">
                <th className="px-2 py-1 text-left font-medium uppercase tracking-wide text-argus-tertiary">
                  Target
                </th>
                <th className="px-2 py-1 text-left font-medium uppercase tracking-wide text-argus-tertiary">
                  Acquirer
                </th>
                <th className="px-2 py-1 text-left font-medium uppercase tracking-wide text-argus-tertiary">
                  Year
                </th>
                <th className="px-2 py-1 text-left font-medium uppercase tracking-wide text-argus-tertiary">
                  Multiple
                </th>
                <th className="px-2 py-1 text-left font-medium uppercase tracking-wide text-argus-tertiary">
                  Source
                </th>
              </tr>
            </thead>
            <tbody>
              {cmps.map((c, i) => (
                <tr key={i} className="border-b border-argus-border-subtle last:border-0">
                  <td className="px-2 py-1 align-top text-argus-primary">{c.target || "—"}</td>
                  <td className="px-2 py-1 align-top text-argus-primary">{c.acquirer || "—"}</td>
                  <td className="px-2 py-1 align-top font-mono tabular-nums text-argus-primary">
                    {c.year ?? "—"}
                  </td>
                  <td className="px-2 py-1 align-top font-mono tabular-nums text-argus-primary">
                    {c.multiple || "—"}
                  </td>
                  <td className="px-2 py-1 align-top text-argus-tertiary">
                    {c.source_citation || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
