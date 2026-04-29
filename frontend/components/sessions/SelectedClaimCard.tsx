"use client";

import { formatVerdict } from "@/lib/formatters";
import { useSelection } from "@/lib/SelectionContext";
import type { ClaimSupportRow, EvidenceObjectRow } from "@/lib/types";

function CloseIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export default function SelectedClaimCard({
  claimSupport,
  evidenceObjects,
}: {
  claimSupport: ClaimSupportRow[];
  evidenceObjects: EvidenceObjectRow[];
}) {
  const { selectedClaimId, setSelectedClaim } = useSelection();
  if (!selectedClaimId) return null;

  const row = claimSupport.find((r) => r.claim_id === selectedClaimId);
  const verdict = formatVerdict(row?.verifier_verdict ?? null);
  const linked = row
    ? evidenceObjects.filter((e) => row.evidence_object_ids?.includes(e.id))
    : [];
  const score =
    typeof row?.entailment_score === "number" ? row.entailment_score : null;

  const meterColor =
    score === null
      ? "bg-argus-neutral"
      : score >= 0.8
        ? "bg-argus-success"
        : score >= 0.6
          ? "bg-argus-accent"
          : score >= 0.4
            ? "bg-argus-warning"
            : "bg-argus-danger";

  return (
    <div
      className="relative rounded-[14px] border-2 bg-elevated p-4 shadow-argus"
      style={{ borderColor: `${verdict.color}66` }}
    >
      <button
        type="button"
        onClick={() => setSelectedClaim(null)}
        aria-label="Clear selection"
        className="absolute right-2 top-2 rounded-argus-sm p-1 text-argus-tertiary transition-colors hover:bg-canvas hover:text-argus-primary"
      >
        <CloseIcon className="h-3.5 w-3.5" />
      </button>

      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-argus-accent" aria-hidden />
        Selected claim
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span
          className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none"
          style={{
            backgroundColor: `${verdict.color}1c`,
            color: verdict.color,
            borderColor: `${verdict.color}55`,
          }}
        >
          {selectedClaimId}
        </span>
        <span
          className="text-[10px] font-medium uppercase tracking-wide"
          style={{ color: verdict.color }}
        >
          {verdict.label}
        </span>
      </div>

      {row?.claim_text ? (
        <p className="mt-2 line-clamp-3 text-[12px] leading-snug text-argus-primary">
          {row.claim_text}
        </p>
      ) : (
        <p className="mt-2 text-[12px] text-argus-tertiary">
          (claim not in current verifier output — try the audit panel)
        </p>
      )}

      {score !== null ? (
        <div className="mt-3">
          <div className="flex items-baseline justify-between text-[10px] text-argus-tertiary">
            <span>Entailment</span>
            <span className="font-mono tabular-nums text-argus-secondary">
              {score.toFixed(2)}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-canvas">
            <div
              className={`h-full transition-all ${meterColor}`}
              style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }}
              aria-hidden
            />
          </div>
        </div>
      ) : null}

      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-argus-sm bg-surface px-2 py-1.5">
          <div className="text-[9px] uppercase tracking-wide text-argus-tertiary">Support</div>
          <div className="mt-0.5 font-medium text-argus-primary">
            {row?.support_type || "—"}
          </div>
        </div>
        <div className="rounded-argus-sm bg-surface px-2 py-1.5">
          <div className="text-[9px] uppercase tracking-wide text-argus-tertiary">Evidence</div>
          <div className="mt-0.5 font-medium text-argus-primary">
            {linked.length} object{linked.length === 1 ? "" : "s"}
          </div>
        </div>
      </div>

      {linked.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {linked.slice(0, 3).map((e) => {
            const conf = (e.confidence || "medium").toLowerCase();
            const dot = e.is_inference
              ? "bg-argus-neutral"
              : conf === "high"
                ? "bg-argus-success"
                : conf === "low"
                  ? "bg-argus-danger"
                  : "bg-argus-warning";
            return (
              <li
                key={e.id}
                className="flex items-start gap-1.5 rounded-argus-sm bg-surface px-2 py-1.5"
              >
                <span className={`mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
                <span className="line-clamp-1 text-[11px] text-argus-secondary">
                  {e.source_title || "Untitled source"}
                </span>
              </li>
            );
          })}
          {linked.length > 3 ? (
            <li className="text-[10px] text-argus-tertiary">+{linked.length - 3} more</li>
          ) : null}
        </ul>
      ) : null}

      {row?.staleness_hint ? (
        <p className="mt-2 text-[10px] text-argus-warning">{row.staleness_hint}</p>
      ) : null}
    </div>
  );
}
