"use client";

import { useMemo, useState } from "react";

import { useSelection } from "@/lib/SelectionContext";
import { runSession } from "@/lib/api";
import type {
  ClaimSupportRow,
  EvidenceObjectRow,
  ExecutiveInsightItem,
  KeyRiskStructuredItem,
  NliLabel,
  NliResult,
  Report,
  SessionDetail,
} from "@/lib/types";

import CaveatBanner, { collectFailures } from "./CaveatBanner";
import { CitationMarker, ConfidencePill } from "./citation";

const MODEL_PALETTE = [
  { name: "Claude", short: "C", color: "#c8842d" },
  { name: "GPT-4", short: "G", color: "#1d4ed8" },
  { name: "Gemini", short: "ge", color: "#15803d" },
  { name: "Grok", short: "gr", color: "#7a1f1f" },
];

function deterministicModel(seed: string): (typeof MODEL_PALETTE)[number] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return MODEL_PALETTE[Math.abs(h) % MODEL_PALETTE.length];
}

function ModelBadge({ seed }: { seed: string }) {
  const m = deterministicModel(seed);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-sm border px-1 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider"
      style={{ color: m.color, borderColor: `${m.color}55`, backgroundColor: `${m.color}10` }}
      title={`Section produced by ${m.name}`}
    >
      <span className="h-1 w-1 rounded-full" style={{ background: m.color }} aria-hidden />
      {m.name}
    </span>
  );
}

/**
 * Decide a confidence level for a claim based on its support row.
 *
 * Phase 1 / Week 2 / Day 5: prefers `ensemble_verdict` (Day 3 aggregator over
 * the LLM judge + DeBERTa NLI + lexical overlap signals) when present.
 * supported_high/_low collapse to "high"; weak collapses to "medium";
 * contradicted/unsupported collapse to "contested". Falls back to the
 * legacy `verifier_verdict` shape if the row pre-dates the Day 3
 * migration so existing engagements render unchanged.
 */
function confidenceLevelFor(claimId: string | null, claimSupport: ClaimSupportRow[]): "high" | "medium" | "contested" {
  if (!claimId) return "medium";
  const row = claimSupport.find((r) => r.claim_id === claimId);
  if (!row) return "medium";
  const ensemble = String(row.ensemble_verdict || "").toLowerCase();
  if (ensemble) {
    if (ensemble === "contradicted" || ensemble === "unsupported") return "contested";
    if (ensemble === "weak") return "medium";
    if (ensemble === "supported_high" || ensemble === "supported_low") return "high";
    // Unknown ensemble vocabulary — fall through to the legacy path.
  }
  const v = String(row.verifier_verdict || "").toLowerCase();
  if (v === "unsupported" || v === "overstates" || row.contradiction_flag) return "contested";
  if (row.weak_or_unsupported || v === "weak" || row.support_type === "inference" || row.support_type === "assumption")
    return "medium";
  return "high";
}

function evidenceById(evidence: EvidenceObjectRow[]): Map<string, EvidenceObjectRow> {
  const m = new Map<string, EvidenceObjectRow>();
  for (const e of evidence) m.set(e.id, e);
  return m;
}

function CitationsFor({
  claimIds,
  claimSupport,
  evidenceMap,
  numbering,
  nliResults,
  verifying,
}: {
  claimIds: string[];
  claimSupport: ClaimSupportRow[];
  evidenceMap: Map<string, EvidenceObjectRow>;
  numbering: Map<string, number>;
  nliResults: NliResult[];
  verifying: boolean;
}) {
  const evIds = useMemo(() => {
    const set = new Set<string>();
    for (const cid of claimIds) {
      const row = claimSupport.find((r) => r.claim_id === cid);
      for (const id of row?.evidence_object_ids ?? []) set.add(id);
    }
    return Array.from(set);
  }, [claimIds, claimSupport]);

  const { setSelectedClaim } = useSelection();

  if (evIds.length === 0) return null;
  return (
    <span className="ml-1 inline-flex items-center gap-0.5 align-middle">
      {evIds.map((id) => {
        const ev = evidenceMap.get(id);
        const n = numbering.get(id) ?? 0;
        return (
          <CitationMarker
            key={id}
            n={n}
            ev={ev}
            nliResults={nliResults}
            verifying={verifying}
            onSelect={() => {
              if (claimIds[0]) setSelectedClaim(claimIds[0]);
            }}
          />
        );
      })}
    </span>
  );
}

function InsightLine({
  text,
  claimIds,
  claimSupport,
  evidenceMap,
  numbering,
  nliResults,
  verifying,
  showWork,
  modelSeed,
}: {
  text: string;
  claimIds: string[];
  claimSupport: ClaimSupportRow[];
  evidenceMap: Map<string, EvidenceObjectRow>;
  numbering: Map<string, number>;
  nliResults: NliResult[];
  verifying: boolean;
  showWork: boolean;
  modelSeed: string;
}) {
  const level = confidenceLevelFor(claimIds[0] ?? null, claimSupport);
  return (
    <li className="flex items-start gap-3 border-l-2 border-argus-border-subtle pl-3 py-1.5 hover:border-argus-accent">
      <ConfidencePill level={level} />
      <div className="min-w-0 flex-1">
        <p className="font-serif text-[14px] leading-relaxed text-argus-primary">
          {text}
          <CitationsFor
            claimIds={claimIds}
            claimSupport={claimSupport}
            evidenceMap={evidenceMap}
            numbering={numbering}
            nliResults={nliResults}
            verifying={verifying}
          />
        </p>
        {showWork ? (
          <div className="mt-1 flex items-center gap-1.5 text-[10px] text-argus-tertiary">
            <ModelBadge seed={modelSeed} />
            <span>· synthesis</span>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function ArgusResponse({
  session,
  showWork,
}: {
  session: SessionDetail;
  showWork: boolean;
}) {
  const report = session.report as Report | null;
  const { setSelectedClaim } = useSelection();

  // Stabilize identities so downstream useMemo deps don't change every render.
  const evidence = useMemo(
    () => session.evidence_objects ?? [],
    [session.evidence_objects],
  );
  const claimSupport = useMemo(
    () => report?.claim_support ?? [],
    [report?.claim_support],
  );
  const structured = report?.structured_answer ?? null;
  const consultingPayload = report?.consulting_payload;

  const evidenceMap = useMemo(() => evidenceById(evidence), [evidence]);

  // Streaming: while the verifier is running we render the answer immediately
  // and let citations resolve from "Verifying…" to their final state.
  const verifying =
    structured?.verification_state === "verifying" ||
    structured?.verification_state === "pending";

  // Project per-claim NLI verdicts onto evidence_object_ids so each citation
  // marker can find its own state. Only includes resolved claims — citations
  // for not-yet-verified claims fall through to "verifying" via the verifying flag.
  const nliResults = useMemo<NliResult[]>(() => {
    const out: NliResult[] = [];
    for (const row of claimSupport) {
      const label = (row.nli_label || "").toLowerCase();
      if (!label || label === "skipped") continue;
      const score = typeof row.nli_confidence === "number" ? row.nli_confidence : 0;
      for (const eid of row.evidence_object_ids ?? []) {
        out.push({ chunk_id: eid, label: label as NliLabel, score });
      }
    }
    return out;
  }, [claimSupport]);

  // Build a stable numbering [N] for each evidence id, in the order they first appear.
  const numbering = useMemo(() => {
    const map = new Map<string, number>();
    let n = 0;
    const recIds = consultingPayload?.recommendation_claim_ids ?? [];
    const insightIds = (consultingPayload?.executive_insights ?? []).flatMap(
      (i) => i.claim_ids ?? [],
    );
    const riskIds = (consultingPayload?.key_risks_structured ?? []).flatMap(
      (r) => r.claim_ids ?? [],
    );
    for (const cid of [...recIds, ...insightIds, ...riskIds]) {
      const row = claimSupport.find((r) => r.claim_id === cid);
      for (const eid of row?.evidence_object_ids ?? []) {
        if (!map.has(eid)) map.set(eid, ++n);
      }
    }
    // Then any remaining evidence
    for (const e of evidence) if (!map.has(e.id)) map.set(e.id, ++n);
    return map;
  }, [consultingPayload, claimSupport, evidence]);

  // Determine overall confidence
  const overallLevel: "high" | "medium" | "contested" = useMemo(() => {
    if (!claimSupport.length) return "medium";
    const counts = { high: 0, medium: 0, contested: 0 };
    for (const r of claimSupport) {
      const v = String(r.verifier_verdict || "").toLowerCase();
      if (v === "unsupported" || v === "overstates" || r.contradiction_flag) counts.contested++;
      else if (r.weak_or_unsupported || v === "weak" || r.support_type === "inference") counts.medium++;
      else counts.high++;
    }
    if (counts.contested > 0) return "contested";
    if (counts.medium > counts.high) return "medium";
    return "high";
  }, [claimSupport]);

  const failures = useMemo(
    () => collectFailures(structured, claimSupport),
    [structured, claimSupport],
  );

  if (!report) return null;

  const insights = consultingPayload?.executive_insights ?? [];
  const risks = consultingPayload?.key_risks_structured ?? [];

  return (
    <article className="space-y-5 border border-argus-border-subtle bg-surface p-6 shadow-argus-sm">
      {/* Verification caveats — surfaces NLI failures and streaming verifier state */}
      <CaveatBanner
        failures={failures}
        verifying={verifying}
        onReview={(claimId) => setSelectedClaim(claimId)}
      />

      {/* TL;DR */}
      <header>
        <div className="mb-2 flex items-center gap-2">
          <span className="argus-label">TL;DR</span>
          <ConfidencePill level={overallLevel} />
          {verifying ? (
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-argus-tertiary">
              <span className="argus-cite-spinner" aria-hidden />
              Verifying claims…
            </span>
          ) : null}
          {showWork ? <ModelBadge seed={`writer:${session.id}`} /> : null}
        </div>
        <p className="font-serif text-[20px] font-semibold leading-snug text-argus-primary">
          {report.recommendation}
        </p>
      </header>

      {/* Summary */}
      {report.summary ? (
        <section>
          <p className="font-serif text-[14px] leading-relaxed text-argus-secondary">
            {report.summary}
          </p>
        </section>
      ) : null}

      {/* Executive insights — each linked to claim_ids → citations */}
      {insights.length > 0 ? (
        <section>
          <h3 className="argus-label mb-2">Executive insights</h3>
          <ul className="space-y-1">
            {insights.map((ins: ExecutiveInsightItem, i: number) => (
              <InsightLine
                key={i}
                text={ins.text ?? ""}
                claimIds={ins.claim_ids ?? []}
                claimSupport={claimSupport}
                evidenceMap={evidenceMap}
                numbering={numbering}
                nliResults={nliResults}
                verifying={verifying}
                showWork={showWork}
                modelSeed={`insight:${i}`}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {/* Key risks */}
      {risks.length > 0 ? (
        <section>
          <h3 className="argus-label mb-2">Key risks</h3>
          <ul className="space-y-1">
            {risks.map((r: KeyRiskStructuredItem, i: number) => (
              <InsightLine
                key={i}
                text={r.text ?? ""}
                claimIds={r.claim_ids ?? []}
                claimSupport={claimSupport}
                evidenceMap={evidenceMap}
                numbering={numbering}
                nliResults={nliResults}
                verifying={verifying}
                showWork={showWork}
                modelSeed={`risk:${i}`}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {/* Next steps */}
      {report.next_steps?.length ? (
        <section>
          <h3 className="argus-label mb-2">Action plan</h3>
          <ol className="space-y-1.5">
            {report.next_steps.map((step, i) => {
              const m = step.match(/^([^:]{1,40}):\s*(.+)$/);
              const when = m?.[1].trim() ?? "";
              const what = m?.[2].trim() ?? step;
              return (
                <li key={i} className="flex items-start gap-3 border-l-2 border-argus-accent/30 pl-3 py-1">
                  <span className="font-mono text-[10px] font-semibold text-argus-accent tabular-nums">{i + 1}</span>
                  <div>
                    {when ? <div className="text-[10px] uppercase tracking-wide text-argus-accent">{when}</div> : null}
                    <p className="font-serif text-[13px] leading-snug text-argus-primary">{what}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {/* Caveats */}
      {report.caveats ? (
        <section className="border-t border-argus-border-subtle pt-4">
          <h3 className="argus-label mb-1">Caveats</h3>
          <p className="text-[12px] leading-relaxed text-argus-tertiary">{report.caveats}</p>
        </section>
      ) : null}

      {/* Footer actions */}
      <footer className="flex flex-wrap items-center gap-3 border-t border-argus-border-subtle pt-3 text-[11px]">
        <button type="button" className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 hover:border-argus-primary">
          Promote to memo
        </button>
        <button type="button" className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 hover:border-argus-primary">
          Promote to deck
        </button>
        <button type="button" className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 hover:border-argus-primary">
          Re-run
        </button>
        <span className="ml-auto text-argus-tertiary">
          {evidence.length} sources · {claimSupport.length} claims reviewed
        </span>
      </footer>
    </article>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-sm border-r-2 border-argus-primary bg-elevated px-3 py-2 font-serif text-[13px] leading-snug text-argus-primary">
        {text}
      </div>
    </div>
  );
}

function ProcessingState({ session }: { session: SessionDetail }) {
  const stages = ["Planner", "Researcher", "Analyst", "Critic", "Verifier", "Writer"];
  const completed = (session.agent_outputs ?? []).map((o) => (o.agent_name || "").toLowerCase());
  return (
    <article className="border border-argus-border-subtle bg-surface p-6">
      <div className="argus-label mb-3">Argus is working</div>
      <ol className="space-y-2 font-mono text-[11px]">
        {stages.map((s) => {
          const isDone = completed.includes(s.toLowerCase());
          return (
            <li key={s} className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-sm ${isDone ? "bg-argus-firm" : "bg-argus-border-subtle"}`} aria-hidden />
              <span className={isDone ? "text-argus-primary" : "text-argus-tertiary"}>{s}</span>
              {isDone ? <span className="ml-auto text-argus-tertiary">done</span> : null}
            </li>
          );
        })}
      </ol>
    </article>
  );
}

function DraftState({ sessionId, canWrite }: { sessionId: string; canWrite: boolean }) {
  const [busy, setBusy] = useState(false);
  return (
    <article className="border border-argus-border-subtle bg-surface p-6 text-center">
      <p className="argus-label mb-2">Draft</p>
      <p className="font-serif text-[15px] text-argus-primary">
        {canWrite
          ? "Engagement created. Run the pipeline to produce the first answer."
          : "Draft engagement. Only members or leads can run the pipeline."}
      </p>
      {canWrite ? (
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await runSession(sessionId);
            } catch {
              setBusy(false);
            }
          }}
          className="mt-4 rounded-sm border border-argus-border-strong bg-argus-primary px-4 py-2 text-[12px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Starting…" : "Run analysis"}
        </button>
      ) : null}
    </article>
  );
}

export default function Conversation({
  session,
  showWork,
}: {
  session: SessionDetail;
  showWork: boolean;
}) {
  const canWrite = session.my_role === "lead" || session.my_role === "member";

  return (
    <section className="argus-pane-center mx-auto flex max-w-[820px] flex-col gap-4 px-6 py-6">
      <UserBubble text={session.query} />

      {session.status === "draft" ? (
        <DraftState sessionId={session.id} canWrite={canWrite} />
      ) : session.report ? (
        // Render the answer as soon as it exists — even if status is still
        // "processing" while the verifier streams NLI results in.
        <ArgusResponse session={session} showWork={showWork} />
      ) : session.status === "processing" || session.status === "pending" ? (
        <ProcessingState session={session} />
      ) : (
        <article className="border border-argus-border-subtle bg-surface p-6 text-center">
          <p className="font-serif text-[14px] text-argus-tertiary">
            No answer produced yet. {session.status === "failed" ? "The pipeline failed — see logs." : ""}
          </p>
        </article>
      )}

      {/* Composer */}
      <footer className="sticky bottom-0 border-t border-argus-border-subtle bg-canvas pt-3">
        <div
          className={`flex items-end gap-2 rounded-sm border bg-surface px-3 py-2 shadow-argus-sm focus-within:border-argus-primary ${
            canWrite ? "border-argus-border-moderate" : "border-argus-border-subtle opacity-60"
          }`}
        >
          <textarea
            placeholder={
              canWrite
                ? "Ask a follow-up. Use /memo, /deck, /model to generate artifacts."
                : "Read-only access — ask a lead to upgrade your role to send messages."
            }
            rows={2}
            disabled={!canWrite}
            className="min-w-0 flex-1 resize-none bg-transparent font-serif text-[13px] leading-snug text-argus-primary placeholder:text-argus-quaternary focus:outline-none disabled:cursor-not-allowed"
          />
          <div className="flex flex-col items-end gap-1.5 text-[10px]">
            <select
              disabled={!canWrite}
              className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 py-0.5 text-[10px] text-argus-secondary focus:outline-none disabled:opacity-60"
              defaultValue="Research"
            >
              <option>Research</option>
              <option>Synthesize</option>
              <option>Critique</option>
              <option>Brainstorm</option>
            </select>
            <button
              type="button"
              disabled={!canWrite}
              className="rounded-sm border border-argus-border-strong bg-argus-primary px-2 py-1 text-[10px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[10px] text-argus-tertiary">
          <span>
            Asking across <span className="text-argus-primary">Engagement + Library</span>
          </span>
          <span className="font-mono tabular-nums">
            {(session.evidence_objects ?? []).length} sources in scope
          </span>
        </div>
      </footer>
    </section>
  );
}
