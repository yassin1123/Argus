import Link from "next/link";
import GapReportView from "@/components/Report/GapReportView";
import ReportView from "@/components/Report/ReportView";
import { formatPipelineStage } from "@/lib/formatters";
import { ProcessingCenter } from "./ProcessingCenter";
import { SessionStatusPill } from "./SessionStatusPill";
import type { GapReport, Report, SessionDetail } from "@/lib/types";

export default function AnswerCanvas({
  session,
  gap,
}: {
  session: SessionDetail;
  gap: GapReport | undefined;
}) {
  const sev = session.metadata?.contradiction_severity;
  const contradictionSeverity = typeof sev === "number" ? sev : undefined;
  const trace = session.metadata?.pipeline_trace;
  const lastTrace =
    Array.isArray(trace) && trace.length > 0
      ? (trace[trace.length - 1] as { event?: string; detail?: string })
      : null;

  return (
    <section className="workspace-answer min-w-0">
      <div className="sticky top-0 z-10 mb-6 border-b border-argus-border-subtle bg-canvas/90 px-1 py-4 backdrop-blur-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate font-serif text-xl font-semibold text-argus-primary">{session.title}</h1>
              <Link
                href={`/sessions/${session.id}/chat`}
                className="shrink-0 text-xs font-semibold text-argus-accent hover:underline"
              >
                Chat
              </Link>
            </div>
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-argus-secondary">
              {session.query}
            </p>
            {session.intake_answers && session.intake_answers.length > 0 ? (
              <p className="mt-2 text-[11px] text-argus-tertiary">
                Analysis incorporates {session.intake_answers.length} intake response
                {session.intake_answers.length === 1 ? "" : "s"}.
              </p>
            ) : null}
          </div>
          <SessionStatusPill status={session.status} />
        </div>
      </div>

      {session.status === "draft" && (
        <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-8 text-center shadow-argus-sm">
          <p className="text-sm text-argus-secondary">
            Session created. Add sources if needed, then run the analysis.
          </p>
        </div>
      )}

      {session.status === "insufficient" && gap && Object.keys(gap).length > 0 && (
        <div className="mb-8">
          <GapReportView gap={gap} />
        </div>
      )}

      {session.status === "insufficient" && (!gap || Object.keys(gap).length === 0) && (
        <div className="mb-8 rounded-[20px] border border-argus-warning-border bg-argus-warning-subtle/50 p-8">
          <p className="font-semibold text-argus-warning">Insufficient evidence</p>
          <p className="mt-2 text-sm text-argus-secondary">
            No gap report payload was returned. Try running again or add more source documents.
          </p>
        </div>
      )}

      {(session.status === "processing" || session.status === "pending") && (
        <ProcessingCenter session={session} />
      )}

      {session.status === "failed" && (
        <div className="rounded-[14px] border border-argus-danger-border bg-argus-danger-subtle p-6">
          <p className="font-semibold text-argus-danger">Analysis failed</p>
          <p className="mt-2 text-sm text-argus-secondary">
            The pipeline encountered an error. Try <strong>Retry analysis</strong> from the trust panel, or check
            server logs.
          </p>
          {lastTrace?.event ? (
            <div className="mt-4 rounded-[10px] border border-argus-danger-border/60 bg-canvas/80 p-3 text-xs text-argus-secondary">
              <p className="font-semibold text-argus-primary">Last recorded step</p>
              <p className="mt-1 text-argus-primary">{formatPipelineStage(lastTrace.event)}</p>
              {lastTrace.detail ? (
                <p className="mt-1 whitespace-pre-wrap text-argus-tertiary">{lastTrace.detail}</p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      {session.report ? (
        <ReportView
          report={session.report as Report}
          contradictionSeverity={contradictionSeverity}
          session={session}
        />
      ) : null}

      {!session.report &&
        session.status !== "insufficient" &&
        session.status !== "draft" &&
        session.status !== "processing" &&
        session.status !== "pending" &&
        session.status !== "failed" && (
          <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-6 text-sm text-argus-secondary shadow-argus-sm">
            No report is available for this session yet.
          </div>
        )}
    </section>
  );
}
