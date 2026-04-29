"use client";

import { useEffect, useRef } from "react";

import { formatVerdict } from "@/lib/formatters";
import { useSelection } from "@/lib/SelectionContext";
import type { ClaimSupportRow } from "@/lib/types";

function bucket(row: ClaimSupportRow): "supported" | "weak" | "unsupported" {
  const v = String(row.verifier_verdict || "").toLowerCase();
  if (v === "unsupported" || v === "overstates" || row.contradiction_flag) return "unsupported";
  if (
    row.weak_or_unsupported ||
    v === "weak" ||
    row.support_type === "inference" ||
    row.support_type === "assumption"
  )
    return "weak";
  return "supported";
}

function StatBlock({
  label,
  count,
  total,
  tone,
}: {
  label: string;
  count: number;
  total: number;
  tone: "success" | "warning" | "danger";
}) {
  const colorMap = {
    success: { bg: "bg-argus-success-subtle", text: "text-argus-success", dot: "bg-argus-success" },
    warning: { bg: "bg-argus-warning-subtle", text: "text-argus-warning", dot: "bg-argus-warning" },
    danger: { bg: "bg-argus-danger-subtle", text: "text-argus-danger", dot: "bg-argus-danger" },
  }[tone];
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className={`rounded-argus-md border border-argus-border-subtle ${colorMap.bg} px-3 py-2`}>
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${colorMap.dot}`} aria-hidden />
        <span className={`text-[10px] font-semibold uppercase tracking-wide ${colorMap.text}`}>
          {label}
        </span>
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="font-mono text-lg text-argus-primary tabular-nums">{count}</span>
        <span className="text-[11px] text-argus-tertiary">of {total}</span>
        <span className="ml-auto text-[10px] text-argus-tertiary tabular-nums">{pct}%</span>
      </div>
    </div>
  );
}

export default function VerifierReport({
  rows,
  onClaimClick,
}: {
  rows: ClaimSupportRow[];
  onClaimClick: (claimId: string) => void;
}) {
  if (!rows?.length) return null;

  const counts = { supported: 0, weak: 0, unsupported: 0 };
  for (const r of rows) counts[bucket(r)]++;
  const total = rows.length;

  return (
    <section className="mb-10 rounded-argus-md border border-argus-border-subtle bg-surface p-6 shadow-argus-sm md:p-8">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Verifier report
          </p>
          <h3 className="mt-1 font-serif text-lg text-argus-primary">
            Every claim re-checked against the evidence catalog
          </h3>
        </div>
        <p className="max-w-xs text-right text-[11px] text-argus-tertiary">
          Click any claim id to open the supporting evidence in a side drawer.
        </p>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-2">
        <StatBlock label="Supported" count={counts.supported} total={total} tone="success" />
        <StatBlock label="Weak" count={counts.weak} total={total} tone="warning" />
        <StatBlock label="Unsupported" count={counts.unsupported} total={total} tone="danger" />
      </div>

      <RowsList rows={rows} onClaimClick={onClaimClick} />
    </section>
  );
}

function RowsList({
  rows,
  onClaimClick,
}: {
  rows: ClaimSupportRow[];
  onClaimClick: (claimId: string) => void;
}) {
  const { selectedClaimId, hoveredClaimId, setHoveredClaim } = useSelection();
  const selectedRowRef = useRef<HTMLLIElement | null>(null);

  // When a claim is selected from elsewhere, scroll its row into view here.
  useEffect(() => {
    if (selectedClaimId && selectedRowRef.current) {
      selectedRowRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedClaimId]);

  return (
    <ul className="divide-y divide-argus-border-subtle">
      {rows.map((row) => {
        const b = bucket(row);
        const verdict = formatVerdict(row.verifier_verdict ?? null);
        const evCount = row.evidence_object_ids?.length ?? 0;
        const cid = row.claim_id || "";
        const isSelected = !!cid && selectedClaimId === cid;
        const isHovered = !!cid && hoveredClaimId === cid;
        return (
            <li
              key={row.claim_id || row.claim_text}
              ref={isSelected ? selectedRowRef : null}
              data-claim-id={cid}
              onMouseEnter={() => cid && setHoveredClaim(cid)}
              onMouseLeave={() => cid && setHoveredClaim(null)}
              className={`flex items-start gap-3 py-3 transition-colors ${
                isSelected ? "-mx-2 rounded-argus-sm bg-elevated px-2" : ""
              } ${isHovered && !isSelected ? "-mx-2 rounded-argus-sm bg-canvas/50 px-2" : ""}`}
            >
              <span
                className="mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: verdict.color }}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {row.claim_id ? (
                    <button
                      type="button"
                      onClick={() => onClaimClick(row.claim_id!)}
                      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium leading-none transition-colors hover:opacity-80"
                      style={{
                        backgroundColor: `${verdict.color}1c`,
                        color: verdict.color,
                        borderColor: `${verdict.color}55`,
                      }}
                    >
                      {row.claim_id}
                    </button>
                  ) : null}
                  <span
                    className="text-[10px] font-medium uppercase tracking-wide"
                    style={{ color: verdict.color }}
                  >
                    {verdict.label}
                  </span>
                  <span className="text-[10px] text-argus-tertiary">
                    {row.support_type || "—"}
                  </span>
                  <span className="ml-auto text-[10px] text-argus-tertiary tabular-nums">
                    {typeof row.entailment_score === "number"
                      ? `entailment ${row.entailment_score.toFixed(2)}`
                      : ""}
                    {evCount ? ` · ${evCount} source${evCount === 1 ? "" : "s"}` : ""}
                  </span>
                </div>
                <p className="mt-1 text-[13px] leading-snug text-argus-secondary">
                  {row.claim_text}
                </p>
                {b === "weak" && row.staleness_hint ? (
                  <p className="mt-1 text-[11px] text-argus-warning">{row.staleness_hint}</p>
                ) : null}
              </div>
            </li>
          );
        })}
    </ul>
  );
}
