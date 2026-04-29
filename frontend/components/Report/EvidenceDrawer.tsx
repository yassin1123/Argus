"use client";

import { useEffect } from "react";

import { formatVerdict } from "@/lib/formatters";
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

export default function EvidenceDrawer({
  open,
  claimId,
  claimSupport,
  evidenceObjects,
  onClose,
}: {
  open: boolean;
  claimId: string | null;
  claimSupport: ClaimSupportRow[];
  evidenceObjects: EvidenceObjectRow[];
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !claimId) return null;

  const claim = claimSupport.find((r) => r.claim_id === claimId) || null;
  const evIds = claim?.evidence_object_ids ?? [];
  const linkedEvidence = evidenceObjects.filter((e) => evIds.includes(e.id));
  const verdict = formatVerdict(claim?.verifier_verdict ?? null);

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm transition-opacity"
      />
      <aside
        role="dialog"
        aria-label={`Evidence for claim ${claimId}`}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col overflow-hidden border-l border-argus-border-subtle bg-canvas shadow-argus-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-argus-border-subtle px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-argus-tertiary">
              <span>Claim {claimId}</span>
              <span
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5"
                style={{ backgroundColor: `${verdict.color}22`, color: verdict.color }}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: verdict.color }} />
                {verdict.label}
              </span>
            </div>
            <p className="mt-2 text-[14px] leading-snug text-argus-primary">
              {claim?.claim_text || "Claim text unavailable."}
            </p>
            {claim ? (
              <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
                <dt className="text-argus-tertiary">support</dt>
                <dd className="text-argus-secondary">{claim.support_type || "—"}</dd>
                <dt className="text-argus-tertiary">entailment</dt>
                <dd className="text-argus-secondary tabular-nums">
                  {typeof claim.entailment_score === "number"
                    ? claim.entailment_score.toFixed(2)
                    : "—"}
                </dd>
                <dt className="text-argus-tertiary">evidence</dt>
                <dd className="text-argus-secondary">{linkedEvidence.length} object(s)</dd>
              </dl>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-argus-sm p-1 text-argus-tertiary transition-colors hover:bg-elevated hover:text-argus-primary"
            aria-label="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {linkedEvidence.length === 0 ? (
            <p className="text-[13px] text-argus-tertiary">
              No evidence objects are linked to this claim. The audit panel may have additional
              context.
            </p>
          ) : (
            linkedEvidence.map((e) => (
              <article
                key={e.id}
                className="rounded-argus-md border border-argus-border-subtle bg-surface p-4"
              >
                <div className="flex items-center justify-between gap-2 text-[10px] font-medium uppercase tracking-wide text-argus-tertiary">
                  <span>{e.source_type || "source"}</span>
                  <span>
                    {e.confidence || "medium"} confidence
                    {e.is_inference ? " · inference" : ""}
                  </span>
                </div>
                <h4 className="mt-1.5 text-[13px] font-medium text-argus-primary">
                  {e.source_title || "Untitled source"}
                </h4>
                {e.quote ? (
                  <blockquote className="mt-2 border-l-2 border-argus-border-moderate pl-3 text-[12px] italic leading-relaxed text-argus-secondary">
                    “{e.quote}”
                  </blockquote>
                ) : null}
                {e.source_url ? (
                  <a
                    href={e.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-block text-[11px] text-argus-accent hover:underline"
                  >
                    Open source ↗
                  </a>
                ) : null}
              </article>
            ))
          )}
          {claim?.staleness_hint ? (
            <div className="rounded-argus-md border border-dashed border-argus-warning-border/60 bg-argus-warning-subtle/40 p-3 text-[12px] text-argus-warning">
              <strong>Note:</strong> {claim.staleness_hint}
            </div>
          ) : null}
        </div>
      </aside>
    </>
  );
}
