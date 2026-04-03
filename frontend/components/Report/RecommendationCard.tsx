"use client";

import { useState } from "react";
import type { Report, SessionDetail } from "@/lib/types";
import { AnimatedExpand } from "@/components/ui/AnimatedExpand";

function confidenceBars(level: string): { filled: number; hint: string } {
  const l = (level || "").toLowerCase();
  if (l.includes("high") && !l.includes("medium")) return { filled: 4, hint: "Strong evidentiary base" };
  if (l.includes("medium-high") || l.includes("medium high"))
    return { filled: 3, hint: "Solid but not exhaustive" };
  if (l.includes("medium")) return { filled: 2, hint: "Limited quantitative depth" };
  if (l.includes("low")) return { filled: 1, hint: "Thin or contested evidence" };
  return { filled: 2, hint: "" };
}

function totalPipelineSeconds(session: SessionDetail | undefined): number | null {
  if (!session?.agent_outputs?.length) return null;
  let t = 0;
  for (const o of session.agent_outputs) {
    if (typeof o.duration_ms === "number" && o.duration_ms > 0) t += o.duration_ms;
  }
  return t > 0 ? Math.round(t / 1000) : null;
}

export default function RecommendationCard({
  report,
  session,
}: {
  report: Report;
  session?: SessionDetail;
}) {
  const [openWWC, setOpenWWC] = useState(false);
  const wwcm = report.consulting_payload?.what_would_change_our_mind;
  const { filled, hint } = confidenceBars(report.confidence_level);
  const sources = report.evidence_count ?? session?.evidence_objects?.length ?? 0;
  const claims = report.claim_support?.length ?? 0;
  const verified =
    report.claim_support?.filter((c) => {
      const v = String(c.verifier_verdict || "").toLowerCase();
      return v === "supported" || v === "weak";
    }).length ?? 0;
  const secs = totalPipelineSeconds(session);
  const intake = session?.intake_answers?.length
    ? `Grounded in ${session.intake_answers.length} intake response${session.intake_answers.length === 1 ? "" : "s"}.`
    : null;

  return (
    <div className="relative mb-10 overflow-hidden rounded-[20px] border border-argus-border-subtle bg-surface shadow-recommendation">
      <div className="absolute inset-y-0 left-0 w-1.5 bg-argus-gold" aria-hidden />
      <div className="px-6 py-8 md:px-10 md:py-12">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-argus-tertiary">
            Recommendation
          </span>
          <div className="flex items-center gap-1" title={hint || report.confidence_level} aria-label="Confidence">
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className={`h-2 w-6 rounded-sm ${i < filled ? "bg-argus-accent" : "bg-argus-border-moderate"}`}
              />
            ))}
          </div>
          <span className="text-xs font-medium text-argus-secondary">{report.confidence_level}</span>
        </div>

        <h2 className="mt-4 font-serif text-[clamp(1.5rem,4vw,2.25rem)] font-semibold leading-[1.25] tracking-[-0.02em] text-argus-primary">
          {report.recommendation}
        </h2>

        <p className="mt-5 text-base leading-[1.75] text-argus-secondary">{report.summary}</p>

        <p className="mt-4 text-xs text-argus-tertiary">
          Based on {sources} source{sources !== 1 ? "s" : ""}
          {claims > 0 ? ` · ${verified} of ${claims} claims reviewed` : ""}
          {secs != null ? ` · Analysis completed in ${secs}s` : ""}
          {intake ? ` · ${intake}` : ""}
        </p>

        {wwcm ? (
          <div className="mt-6 rounded-[14px] border border-argus-info-border bg-argus-info-subtle/30">
            <button
              type="button"
              onClick={() => setOpenWWC(!openWWC)}
              className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-argus-primary"
              aria-expanded={openWWC}
            >
              What would change this?
              <span className="text-argus-tertiary">{openWWC ? "−" : "+"}</span>
            </button>
            <AnimatedExpand show={openWWC}>
              <p className="border-t border-argus-border-subtle px-4 pb-4 pt-3 text-sm leading-relaxed text-argus-secondary">
                {wwcm}
              </p>
            </AnimatedExpand>
          </div>
        ) : null}

        <p className="mt-4 text-xs text-argus-tertiary">
          Verify material claims in the evidence and claim panels before external use.
        </p>
      </div>
    </div>
  );
}
