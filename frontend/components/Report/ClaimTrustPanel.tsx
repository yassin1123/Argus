"use client";

import { useState } from "react";
import { formatVerdict } from "@/lib/formatters";
import type { ClaimSupportRow } from "@/lib/types";
import { AnimatedExpand } from "@/components/ui/AnimatedExpand";

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function TrustDot({ type }: { type: "supported" | "inferred" | "flagged" }) {
  const bg =
    type === "supported"
      ? "bg-argus-success"
      : type === "inferred"
        ? "bg-argus-warning"
        : "bg-argus-danger";
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${bg}`} aria-hidden />;
}

function bucketRows(rows: ClaimSupportRow[]) {
  const weak = rows.filter((r) => {
    if (r.support_type === "assumption") return false;
    const v = String(r.verifier_verdict || "").toLowerCase();
    const nli = String(r.nli_label || "").toLowerCase();
    return (
      r.weak_or_unsupported ||
      r.contradiction_flag ||
      r.support_type === "inference" ||
      v === "weak" ||
      v === "unsupported" ||
      v === "overstates" ||
      nli === "contradicts" ||
      nli === "insufficient"
    );
  });
  const weakSet = new Set(weak);
  const supported = rows.filter(
    (r) =>
      r.support_type !== "assumption" &&
      !weakSet.has(r) &&
      (r.support_type === "direct_quote" ||
        r.support_type === "paraphrase" ||
        (r.evidence_object_ids?.length ?? 0) > 0)
  );
  const supportedSet = new Set(supported);
  const flaggedSet = new Set(weak);
  const inferred = rows.filter((r) => !supportedSet.has(r) && !flaggedSet.has(r));
  return { supported, inferred, flagged: weak };
}

function ClaimRow({
  claim,
  bucket,
  claimIndex,
}: {
  claim: ClaimSupportRow;
  bucket: "supported" | "inferred" | "flagged";
  claimIndex: number;
}) {
  const n = claim.evidence_object_ids?.length ?? 0;
  const vd = formatVerdict(claim.verifier_verdict ?? null);
  return (
    <div className="flex items-start gap-3 py-2.5">
      <TrustDot type={bucket} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold text-argus-tertiary">#{claimIndex}</span>
          <span
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
            style={{ backgroundColor: `${vd.color}18`, color: vd.color }}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: vd.color }} />
            {vd.label}
          </span>
        </div>
        <p className="mt-1 text-sm text-argus-primary">{claim.claim_text}</p>
      </div>
      <span className="shrink-0 text-xs text-argus-tertiary">
        {n} source{n !== 1 ? "s" : ""}
      </span>
    </div>
  );
}

export function ClaimTrustPanel({ rows }: { rows: ClaimSupportRow[] }) {
  const [open, setOpen] = useState(false);
  if (!rows?.length) return null;

  const { supported, inferred, flagged } = bucketRows(rows);
  const total = rows.length;

  return (
    <div className="mb-10 border-t border-argus-border-subtle pt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 py-3 text-xs font-medium text-argus-tertiary transition-colors duration-150 hover:text-argus-secondary"
      >
        <Chevron open={open} />
        {open ? "Hide" : "Show"} claim analysis ({total} claims)
      </button>
      <AnimatedExpand show={open}>
        <div className="rounded-[14px] border border-argus-border-subtle bg-canvas/40 px-4 py-3">
          {supported.length > 0 && (
            <div className="border-b border-argus-border-subtle pb-2">
              <p className="py-2 text-[11px] font-semibold uppercase tracking-wide text-argus-success">
                Supported
              </p>
              {supported.map((r, i) => (
                <ClaimRow
                  key={r.claim_id ?? i}
                  claim={r}
                  bucket="supported"
                  claimIndex={rows.findIndex((x) => x === r) + 1}
                />
              ))}
            </div>
          )}
          {inferred.length > 0 && (
            <div className="border-b border-argus-border-subtle py-2">
              <p className="py-2 text-[11px] font-semibold uppercase tracking-wide text-argus-warning">
                Inferred or assumptions
              </p>
              {inferred.map((r, i) => (
                <ClaimRow
                  key={r.claim_id ?? i}
                  claim={r}
                  bucket="inferred"
                  claimIndex={rows.findIndex((x) => x === r) + 1}
                />
              ))}
            </div>
          )}
          {flagged.length > 0 && (
            <div className="pt-2">
              <p className="py-2 text-[11px] font-semibold uppercase tracking-wide text-argus-danger">
                Flagged
              </p>
              {flagged.map((r, i) => (
                <ClaimRow
                  key={r.claim_id ?? i}
                  claim={r}
                  bucket="flagged"
                  claimIndex={rows.findIndex((x) => x === r) + 1}
                />
              ))}
            </div>
          )}
        </div>
      </AnimatedExpand>
    </div>
  );
}
