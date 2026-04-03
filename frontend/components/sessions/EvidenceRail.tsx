"use client";

import { useState } from "react";
import { AnimatedExpand } from "@/components/ui/AnimatedExpand";
import RetrievalHitsPanel from "@/components/Report/RetrievalHitsPanel";
import { formatSourceLabel } from "@/lib/formatters";
import type { EvidenceObjectRow, RetrievalTaskSnapshot, SessionDetail } from "@/lib/types";
import { EvidenceCard } from "./EvidenceCard";

const EVIDENCE_PREVIEW = 6;

export default function EvidenceRail({ session }: { session: SessionDetail }) {
  const [showAllEvidence, setShowAllEvidence] = useState(false);
  const hits = session.metadata?.retrieval_hits;
  const hasHits = Array.isArray(hits) && hits.length > 0;
  const hasFiles = (session.uploaded_files?.length ?? 0) > 0;
  const evidenceList = session.evidence_objects ?? [];
  const hasEvidence = evidenceList.length > 0;
  const sev = session.metadata?.contradiction_severity;
  const showContradiction =
    typeof sev === "number" && sev > 0 && session.status === "complete";

  const preview = evidenceList.slice(0, EVIDENCE_PREVIEW);
  const overflow = evidenceList.slice(EVIDENCE_PREVIEW);
  const hasOverflow = overflow.length > 0;

  const topSources =
    session.status === "complete" && evidenceList.length > 0
      ? [...evidenceList]
          .sort((a, b) => (Number(b.source_score) || 0) - (Number(a.source_score) || 0))
          .slice(0, 5)
      : [];

  return (
    <aside className="flex flex-col gap-4">
      <div className="sticky top-0 z-10 flex items-center justify-between bg-canvas pb-3 pt-1">
        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
          Evidence
        </span>
        {hasEvidence ? (
          <span className="rounded-full bg-argus-neutral-subtle px-2 py-0.5 text-[10px] font-semibold text-argus-neutral">
            {evidenceList.length}
          </span>
        ) : null}
      </div>

      {!hasFiles && !hasHits && !hasEvidence && !showContradiction && (
        <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 text-sm text-argus-secondary shadow-argus-sm">
          Inputs and retrieval will appear here as the pipeline runs.
        </div>
      )}

      {hasFiles && (
        <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">Inputs</p>
          <ul className="mt-2 space-y-1 text-sm text-argus-primary">
            {session.uploaded_files!.map((f) => (
              <li key={f.id} className="truncate" title={f.filename}>
                {f.filename}
              </li>
            ))}
          </ul>
        </div>
      )}

      {showContradiction && (
        <div className="rounded-[12px] border border-argus-warning-border bg-argus-warning-subtle px-3 py-3 text-sm">
          <p className="font-semibold text-argus-warning">Tension signal</p>
          <p className="mt-1 text-xs text-argus-tertiary">
            Severity {sev}. Confidence may be capped; see caveats and verification.
            {Array.isArray(session.metadata?.research_contradictions) &&
            session.metadata!.research_contradictions!.length > 0
              ? ` ${session.metadata!.research_contradictions!.length} research tensions noted.`
              : null}
          </p>
        </div>
      )}

      {hasHits && (
        <RetrievalHitsPanel snapshots={hits as RetrievalTaskSnapshot[]} />
      )}

      {session.status === "processing" && hasHits && (
        <p className="text-[11px] leading-snug text-argus-tertiary">
          Retrieval snapshots update as each research task runs. Citeable rows appear after extraction
          finishes.
        </p>
      )}

      {topSources.length > 0 && (
        <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Top sources
          </p>
          <ul className="mt-2 space-y-3">
            {topSources.map((o) => {
              const label = formatSourceLabel({
                title: o.source_title,
                source_url: o.source_url,
                url: o.source_url,
              });
              const quote = (o.quote || o.claim || "").trim().slice(0, 120);
              return (
                <li key={o.id} className="text-xs">
                  <p className="font-medium text-argus-primary">{label}</p>
                  {quote ? <p className="mt-0.5 text-argus-tertiary line-clamp-2">{quote}…</p> : null}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {hasEvidence && (
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Citeable sources
          </p>
          <ul className="space-y-0">
            {preview.map((o) => (
              <li key={o.id}>
                <EvidenceCard o={o as EvidenceObjectRow} />
              </li>
            ))}
          </ul>
          {hasOverflow && (
            <>
              <button
                type="button"
                onClick={() => setShowAllEvidence((v) => !v)}
                className="mt-2 w-full py-2 text-left text-xs font-medium text-argus-tertiary transition-colors duration-150 hover:text-argus-secondary"
                aria-expanded={showAllEvidence}
              >
                {showAllEvidence
                  ? "Show less"
                  : `Show all (${evidenceList.length})`}
              </button>
              <AnimatedExpand show={showAllEvidence}>
                <ul className="space-y-0 pt-1">
                  {overflow.map((o) => (
                    <li key={o.id}>
                      <EvidenceCard o={o as EvidenceObjectRow} />
                    </li>
                  ))}
                </ul>
              </AnimatedExpand>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
