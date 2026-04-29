"use client";

import { useMemo, useState } from "react";

import { useClaimHighlight, useSelection } from "@/lib/SelectionContext";
import { formatVerdict } from "@/lib/formatters";
import type { ClaimSupportRow, EvidenceObjectRow, Report } from "@/lib/types";

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

function ConfidenceMeter({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const color =
    pct >= 80 ? "bg-argus-success" : pct >= 60 ? "bg-argus-accent" : pct >= 40 ? "bg-argus-warning" : "bg-argus-danger";
  return (
    <div className="h-1 w-16 overflow-hidden rounded-full bg-canvas/80" aria-label={`Entailment ${pct.toFixed(0)}%`}>
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} aria-hidden />
    </div>
  );
}

function EvidenceLeaf({ ev }: { ev: EvidenceObjectRow }) {
  const isInference = !!ev.is_inference;
  const conf = (ev.confidence || "medium").toLowerCase();
  const dot = isInference
    ? "bg-argus-neutral"
    : conf === "high"
      ? "bg-argus-success"
      : conf === "low"
        ? "bg-argus-danger"
        : "bg-argus-warning";

  return (
    <li className="relative pl-5">
      <span className="absolute left-0 top-2 h-px w-3 bg-argus-border-subtle" aria-hidden />
      <span className="absolute left-3 top-2 inline-block h-1.5 w-1.5 rounded-full bg-argus-border-moderate" aria-hidden />
      <div className="rounded-argus-sm border border-argus-border-subtle bg-surface px-3 py-2 hover:border-argus-border-moderate">
        <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wide text-argus-tertiary">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
          <span>{ev.source_type || "source"}</span>
          <span className="text-argus-border-moderate">·</span>
          <span>
            {conf} confidence
            {isInference ? " · inference" : ""}
          </span>
        </div>
        <div className="mt-1 line-clamp-1 text-[12px] font-medium text-argus-primary">
          {ev.source_title || "Untitled source"}
        </div>
        {ev.quote ? (
          <blockquote className="mt-1 line-clamp-2 border-l-2 border-argus-border-subtle pl-2 text-[11px] italic leading-snug text-argus-secondary">
            “{ev.quote}”
          </blockquote>
        ) : null}
      </div>
    </li>
  );
}

function ClaimBranch({
  row,
  evidenceObjects,
  expandedDefault,
}: {
  row: ClaimSupportRow;
  evidenceObjects: EvidenceObjectRow[];
  expandedDefault: boolean;
}) {
  const cid = row.claim_id || "";
  const { isActive, isSelected } = useClaimHighlight(cid);
  const { setSelectedClaim, setHoveredClaim } = useSelection();
  const [expanded, setExpanded] = useState(expandedDefault);

  const verdict = formatVerdict(row.verifier_verdict ?? null);
  const b = bucket(row);

  const linked = useMemo(() => {
    const ids = new Set(row.evidence_object_ids ?? []);
    return evidenceObjects.filter((e) => ids.has(e.id));
  }, [row.evidence_object_ids, evidenceObjects]);

  const toneAccent =
    b === "supported"
      ? "border-argus-success-border"
      : b === "weak"
        ? "border-argus-warning-border"
        : "border-argus-danger-border";

  const ringActive = isActive ? "ring-2 ring-argus-accent/60 ring-offset-1 ring-offset-canvas" : "";
  const bgActive = isSelected ? "bg-elevated" : "bg-surface";

  const toggle = () => setExpanded((e) => !e);

  return (
    <li className="relative pl-5">
      {/* Connecting line + node dot */}
      <span
        className={`absolute left-0 top-3 h-px w-3 ${
          b === "supported"
            ? "bg-argus-success/40"
            : b === "weak"
              ? "bg-argus-warning/40"
              : "bg-argus-danger/40"
        }`}
        aria-hidden
      />
      <span
        className={`absolute left-2.5 top-2 inline-block h-2 w-2 rounded-full border-2 border-canvas ${
          b === "supported"
            ? "bg-argus-success"
            : b === "weak"
              ? "bg-argus-warning"
              : "bg-argus-danger"
        }`}
        aria-hidden
      />

      <div
        onMouseEnter={() => setHoveredClaim(cid)}
        onMouseLeave={() => setHoveredClaim(null)}
        className={`rounded-argus-md border ${toneAccent} ${bgActive} ${ringActive} px-3 py-2.5 transition-all`}
      >
        <button
          type="button"
          onClick={toggle}
          className="flex w-full items-start gap-2 text-left"
          aria-expanded={expanded}
        >
          <span
            className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full transition-transform ${
              expanded ? "rotate-90" : ""
            }`}
            style={{ backgroundColor: verdict.color }}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none"
                style={{
                  backgroundColor: `${verdict.color}1c`,
                  color: verdict.color,
                  borderColor: `${verdict.color}55`,
                }}
              >
                {cid || "claim"}
              </span>
              <span
                className="text-[10px] font-medium uppercase tracking-wide"
                style={{ color: verdict.color }}
              >
                {verdict.label}
              </span>
              <span className="text-[10px] text-argus-tertiary">{row.support_type || "—"}</span>
              {typeof row.entailment_score === "number" ? (
                <span className="ml-auto flex items-center gap-1.5 text-[10px] text-argus-tertiary tabular-nums">
                  entailment {row.entailment_score.toFixed(2)}
                  <ConfidenceMeter score={row.entailment_score} />
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[13px] leading-snug text-argus-primary">{row.claim_text}</p>
            {b === "weak" && row.staleness_hint ? (
              <p className="mt-1 text-[11px] text-argus-warning">{row.staleness_hint}</p>
            ) : null}
          </div>
        </button>

        {expanded ? (
          <div className="mt-2.5 border-t border-argus-border-subtle pt-2.5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-argus-tertiary">
                Evidence ({linked.length})
              </span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedClaim(cid);
                }}
                className="text-[10px] font-medium text-argus-accent hover:underline"
              >
                Open in drawer →
              </button>
            </div>
            {linked.length === 0 ? (
              <p className="text-[11px] text-argus-tertiary">
                No evidence objects linked. The claim may rest on inference or assumption.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {linked.map((ev) => (
                  <EvidenceLeaf key={ev.id} ev={ev} />
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export default function DecisionPath({
  report,
  evidenceObjects,
}: {
  report: Report;
  evidenceObjects: EvidenceObjectRow[];
}) {
  const cs = report.claim_support ?? [];
  const cp = report.consulting_payload;
  const recIds = new Set(cp?.recommendation_claim_ids ?? []);

  // Order claims: recommendation-supporting first, then by verdict severity (weak/unsupported last so they stand out at the bottom).
  const ordered = useMemo(() => {
    const score = (r: ClaimSupportRow) => {
      const inRec = recIds.has(r.claim_id || "") ? 0 : 1;
      const b = bucket(r);
      const verdictRank = b === "supported" ? 0 : b === "weak" ? 2 : 3;
      return inRec * 10 + verdictRank;
    };
    return [...cs].sort((a, b) => score(a) - score(b));
  }, [cs, recIds]);

  const supporting = ordered.filter((r) => recIds.has(r.claim_id || ""));
  const peripheral = ordered.filter((r) => !recIds.has(r.claim_id || ""));

  const counts = { supported: 0, weak: 0, unsupported: 0 };
  for (const r of cs) counts[bucket(r)]++;

  if (cs.length === 0) {
    return (
      <div className="rounded-argus-md border border-argus-border-subtle bg-surface p-6 text-sm text-argus-tertiary">
        No claim chain available yet. The decision path will appear once the verifier has assessed
        the analyst&apos;s claims.
      </div>
    );
  }

  return (
    <section className="space-y-6">
      {/* Root: Recommendation */}
      <div className="rounded-argus-md border border-argus-accent/40 bg-elevated p-5 shadow-argus">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-argus-accent">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-argus-accent" aria-hidden />
          Recommendation
          <span className="ml-auto text-[10px] font-normal text-argus-tertiary">
            confidence: {report.confidence_level || "—"}
          </span>
        </div>
        <p className="mt-2 font-serif text-base leading-relaxed text-argus-primary">
          {report.recommendation}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-argus-tertiary">
          <span className="inline-flex items-center gap-1 rounded-argus-sm border border-argus-success-border bg-argus-success-subtle px-1.5 py-0.5">
            <span className="h-1.5 w-1.5 rounded-full bg-argus-success" aria-hidden />
            <span className="text-argus-success">{counts.supported} supported</span>
          </span>
          {counts.weak > 0 ? (
            <span className="inline-flex items-center gap-1 rounded-argus-sm border border-argus-warning-border bg-argus-warning-subtle px-1.5 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-argus-warning" aria-hidden />
              <span className="text-argus-warning">{counts.weak} weak</span>
            </span>
          ) : null}
          {counts.unsupported > 0 ? (
            <span className="inline-flex items-center gap-1 rounded-argus-sm border border-argus-danger-border bg-argus-danger-subtle px-1.5 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-argus-danger" aria-hidden />
              <span className="text-argus-danger">{counts.unsupported} unsupported</span>
            </span>
          ) : null}
          <span className="ml-auto">{cs.length} claims · {evidenceObjects.length} evidence objects</span>
        </div>
      </div>

      {supporting.length > 0 ? (
        <div>
          <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-secondary">
            Supporting claims
            <span className="text-argus-tertiary">({supporting.length})</span>
          </h3>
          <ul className="space-y-2 border-l-2 border-argus-border-subtle pl-2">
            {supporting.map((row) => (
              <ClaimBranch
                key={row.claim_id || row.claim_text}
                row={row}
                evidenceObjects={evidenceObjects}
                expandedDefault={bucket(row) !== "supported"}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {peripheral.length > 0 ? (
        <div>
          <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-secondary">
            Other verified claims
            <span className="text-argus-tertiary">({peripheral.length})</span>
          </h3>
          <ul className="space-y-2 border-l-2 border-argus-border-subtle pl-2">
            {peripheral.map((row) => (
              <ClaimBranch
                key={row.claim_id || row.claim_text}
                row={row}
                evidenceObjects={evidenceObjects}
                expandedDefault={false}
              />
            ))}
          </ul>
        </div>
      ) : null}

      <ActionPlan report={report} />

      <p className="text-[11px] text-argus-tertiary">
        Hover any claim to highlight it across the workspace; click to open the full evidence drawer.
      </p>
    </section>
  );
}

function ActionPlan({ report }: { report: Report }) {
  const next = report.next_steps ?? [];
  const cp = report.consulting_payload ?? {};
  const kill = cp.kill_criteria ?? [];
  const wwcm = cp.what_would_change_our_mind ?? "";

  if (next.length === 0 && kill.length === 0 && !wwcm) return null;

  // Detect time-bound prefixes ("This week:", "Within 30 days:", "Month 5:", etc.)
  const splitStep = (s: string): { when: string; what: string } => {
    const m = s.match(/^([^:]{1,40}):\s*(.+)$/);
    if (m) return { when: m[1].trim(), what: m[2].trim() };
    return { when: "", what: s };
  };

  return (
    <div className="space-y-4">
      {next.length > 0 ? (
        <div className="rounded-argus-md border border-argus-accent/30 bg-elevated p-5 shadow-argus">
          <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-accent">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-argus-accent" aria-hidden />
            Action plan
            <span className="ml-auto text-[10px] font-normal text-argus-tertiary">
              {next.length} step{next.length === 1 ? "" : "s"}
            </span>
          </div>
          <ol className="space-y-2">
            {next.map((step, i) => {
              const { when, what } = splitStep(step);
              return (
                <li
                  key={i}
                  className="flex items-start gap-3 rounded-argus-sm bg-surface px-3 py-2"
                >
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-argus-accent/15 text-[10px] font-mono font-semibold text-argus-accent">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    {when ? (
                      <div className="text-[10px] font-medium uppercase tracking-wide text-argus-accent">
                        {when}
                      </div>
                    ) : null}
                    <p className="text-[13px] leading-snug text-argus-primary">{what}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      {kill.length > 0 ? (
        <div className="rounded-argus-md border border-argus-danger-border/40 bg-argus-danger-subtle/40 p-5">
          <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-danger">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-argus-danger" aria-hidden />
            Kill criteria
            <span className="ml-auto text-[10px] font-normal text-argus-tertiary">
              if any trigger, reverse the recommendation
            </span>
          </div>
          <ul className="space-y-1.5">
            {kill.map((k, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-[12px] leading-snug text-argus-secondary"
              >
                <span className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full bg-argus-danger" aria-hidden />
                <span>{k}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {wwcm ? (
        <div className="rounded-argus-md border border-argus-warning-border/30 bg-argus-warning-subtle/30 p-4">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-warning">
            What would change our mind
          </div>
          <p className="text-[12px] leading-relaxed text-argus-secondary">{wwcm}</p>
        </div>
      ) : null}
    </div>
  );
}
