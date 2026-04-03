import type { Report, SessionDetail } from "@/lib/types";
import { AuditPanel } from "./AuditPanel";
import { ClaimTrustPanel } from "./ClaimTrustPanel";
import { ConsultingFrame } from "./ConsultingFrame";
import EvidencePanel from "./EvidencePanel";
import { FindingCard } from "./FindingCard";
import { NextStepRow } from "./NextStepRow";
import RecommendationCard from "./RecommendationCard";
import { RiskCard } from "./RiskCard";
import { TensionNotice } from "./TensionNotice";

function SectionLabel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      className={`mb-4 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary ${className}`}
    >
      {children}
    </p>
  );
}

export default function ReportView({
  report,
  contradictionSeverity,
  session,
}: {
  report: Report;
  contradictionSeverity?: number;
  session?: SessionDetail;
}) {
  const cp = report.consulting_payload;
  const cs = report.claim_support ?? [];

  return (
    <article>
      <RecommendationCard report={report} session={session} />

      {report.key_reasons?.length ? (
        <section className="mb-10">
          <SectionLabel>Key findings</SectionLabel>
          {report.key_reasons.map((text, i) => (
            <FindingCard key={i} index={i} text={text} />
          ))}
        </section>
      ) : null}

      {((report.risks?.length ?? 0) > 0 || (contradictionSeverity ?? 0) > 0) && (
        <section className="mb-10">
          <SectionLabel>Risks</SectionLabel>
          {typeof contradictionSeverity === "number" && contradictionSeverity > 0 ? (
            <TensionNotice severity={contradictionSeverity} />
          ) : null}
          {report.risks?.map((text, i) => <RiskCard key={i} text={text} />)}
        </section>
      )}

      {report.next_steps?.length ? (
        <section className="mb-10 rounded-[14px] border border-argus-border-subtle bg-surface px-6 py-6 shadow-argus-sm">
          <SectionLabel>Next steps</SectionLabel>
          {report.next_steps.map((text, i) => (
            <NextStepRow key={i} n={i + 1} text={text} />
          ))}
        </section>
      ) : null}

      {cp && Object.keys(cp).length > 0 ? <ConsultingFrame cp={cp} /> : null}

      {report.counterarguments?.length ? (
        <section className="mb-10">
          <SectionLabel>Counterarguments</SectionLabel>
          <div className="space-y-3 rounded-[14px] border border-argus-border-subtle bg-surface p-6 shadow-argus-sm">
            {report.counterarguments.map((text, i) => (
              <p key={i} className="text-sm leading-[1.65] text-argus-secondary">
                {text}
              </p>
            ))}
          </div>
        </section>
      ) : null}

      {report.sources?.length ? (
        <section className="mb-10">
          <SectionLabel>Sources</SectionLabel>
          <ul className="space-y-2 rounded-[14px] border border-argus-border-subtle bg-surface p-6 shadow-argus-sm">
            {report.sources.map((s, i) => (
              <li key={i} className="text-sm text-argus-primary">
                <span className="font-medium">{s.title}</span>
                <span className="ml-2 text-xs text-argus-tertiary">({s.type})</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {report.caveats ? (
        <section className="mb-10 rounded-[14px] border border-argus-border-subtle bg-canvas/60 p-6">
          <SectionLabel>Caveats</SectionLabel>
          <p className="text-sm leading-relaxed text-argus-secondary">{report.caveats}</p>
        </section>
      ) : null}

      <EvidencePanel items={report.evidence_bundle ?? []} />

      {cs.length > 0 ? <ClaimTrustPanel rows={cs} /> : null}

      <AuditPanel
        verification={report.verification}
        reasoningGraph={report.reasoning_graph}
        claimSupport={cs}
      />
    </article>
  );
}
