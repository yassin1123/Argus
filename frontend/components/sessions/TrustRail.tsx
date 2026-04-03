"use client";

import AgentTimeline from "@/components/Report/AgentTimeline";
import { Button } from "@/components/ui/Button";
import type { ExportFormat } from "@/lib/api";
import { formatPipelineStage } from "@/lib/formatters";
import type { SessionDetail } from "@/lib/types";

export type PipelineTraceEntry = {
  event?: string;
  detail?: string;
  at?: string;
};

function formatMode(mode?: string): string {
  if (!mode) return "General";
  return mode
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function FileTextIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
    </svg>
  );
}

function FileCheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6M9 15l2 2 4-4" />
    </svg>
  );
}

function BookOpenIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M2 3h6a4 4 0 014 4v14a4 4 0 00-4-4H2zM22 3h-6a4 4 0 00-4 4v14a4 4 0 014-4h6z" />
    </svg>
  );
}

function PresentationIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M2 3h20v14H2zM12 17v4M8 21h8" />
    </svg>
  );
}

const FORMATS: {
  id: ExportFormat;
  label: string;
  Icon: typeof FileTextIcon;
}[] = [
  { id: "pdf", label: "PDF", Icon: FileTextIcon },
  { id: "memo", label: "Memo", Icon: FileCheckIcon },
  { id: "client", label: "Report", Icon: BookOpenIcon },
  { id: "pptx", label: "Deck", Icon: PresentationIcon },
];

function Spinner({ className = "text-white" }: { className?: string }) {
  return (
    <svg className={`h-3.5 w-3.5 animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

function QualityMetricsCard({ session }: { session: SessionDetail }) {
  const report = session.report;
  const sources =
    report?.evidence_count ?? session.evidence_objects?.length ?? 0;
  const claims = report?.claim_support?.length ?? 0;
  const verified =
    report?.claim_support?.filter((c) => {
      const v = String(c.verifier_verdict || "").toLowerCase();
      return v === "supported" || v === "weak";
    }).length ?? 0;
  const conf = report?.confidence_level ?? "—";
  const sourceHint =
    sources >= 20 ? "Strong evidence base" : sources >= 8 ? "Solid coverage" : "Narrow source set";
  const claimLine =
    claims > 0 ? `${verified} of ${claims} reviewed` : "—";
  const claimHint =
    claims > 0 && verified / claims < 0.5 ? "Several items need attention" : "Mostly aligned with evidence";
  const confLower = conf.toLowerCase();
  const confHint =
    confLower.includes("low") || confLower.includes("medium")
      ? `${conf} — add proprietary data to tighten confidence`
      : `${conf} — evidence supports the call`;

  const metrics = [
    {
      value: String(sources),
      label: "Sources",
      sub: sourceHint,
    },
    {
      value: claimLine,
      label: "Claims",
      sub: claims ? claimHint : "",
    },
    {
      value: conf,
      label: "Confidence",
      sub: confHint,
    },
  ];

  return (
    <div className="grid grid-cols-3 divide-x divide-argus-border-subtle rounded-[14px] border border-argus-border-subtle bg-surface shadow-argus-sm">
      {metrics.map((m) => (
        <div key={m.label} className="flex flex-col items-center px-2 py-4">
          <span className="font-serif text-xl font-semibold text-argus-primary">{m.value}</span>
          <span className="mt-1 text-center text-[10px] font-semibold uppercase tracking-wide text-argus-tertiary">
            {m.label}
          </span>
          {m.sub ? (
            <span className="mt-1 text-center text-[9px] leading-tight text-argus-tertiary">{m.sub}</span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default function TrustRail({
  session,
  exportFmt,
  setExportFmt,
  exportLoading,
  onExport,
  runLoading,
  onRun,
  loadError,
}: {
  session: SessionDetail;
  exportFmt: ExportFormat;
  setExportFmt: (f: ExportFormat) => void;
  exportLoading: boolean;
  onExport: () => void;
  runLoading: boolean;
  onRun: () => void;
  loadError: string | null;
}) {
  const trace = session.metadata?.pipeline_trace;
  const curated =
    Array.isArray(trace) && trace.length > 0
      ? (trace as PipelineTraceEntry[]).slice(-12)
      : [];

  const primaryLabel = () => {
    if (session.status === "processing" || session.status === "pending")
      return "Running…";
    if (session.status === "failed") return "Retry analysis";
    if (session.status === "insufficient") return "Add sources and retry";
    if (session.status === "complete") return "Run again";
    return "Run analysis";
  };

  const primaryDisabled =
    runLoading || session.status === "processing" || session.status === "pending";

  const exportLabel =
    FORMATS.find((f) => f.id === exportFmt)?.label ?? exportFmt;

  return (
    <aside className="flex flex-col gap-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
        Trust & actions
      </p>

      <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
        <p className="text-[11px] text-argus-tertiary">
          Mode: <span className="text-argus-secondary">{formatMode(session.report_mode)}</span>
        </p>
        <div className="mt-3">
          {session.status === "complete" ? (
            <Button variant="outline" className="w-full" onClick={onRun} disabled={primaryDisabled}>
              {runLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <Spinner className="text-argus-primary" />
                  Starting…
                </span>
              ) : (
                primaryLabel()
              )}
            </Button>
          ) : (
            <button
              type="button"
              onClick={onRun}
              disabled={primaryDisabled}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-[10px] bg-ink text-sm font-semibold text-white transition-colors duration-150 hover:bg-ink-muted disabled:cursor-not-allowed disabled:opacity-70"
            >
              {runLoading || session.status === "processing" || session.status === "pending" ? (
                <>
                  <Spinner />
                  Running…
                </>
              ) : (
                primaryLabel()
              )}
            </button>
          )}
        </div>
      </div>

      {session.status === "complete" && session.report && (
        <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Export
          </p>
          <div className="rounded-[12px] bg-argus-neutral-subtle p-1">
            <div className="grid grid-cols-4 gap-1">
              {FORMATS.map(({ id, label, Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setExportFmt(id)}
                  className={`flex flex-col items-center gap-1 rounded-[8px] px-2 py-2 text-[10px] font-semibold transition-all duration-100 ${
                    exportFmt === id
                      ? "bg-surface text-argus-primary shadow-[0_1px_3px_rgba(10,10,15,0.1)]"
                      : "text-argus-tertiary hover:text-argus-secondary"
                  }`}
                  aria-pressed={exportFmt === id}
                  aria-label={`Export as ${label}`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </div>
          </div>
          <Button
            variant="ghost"
            className="mt-3 h-9 w-full border border-argus-border-subtle"
            onClick={onExport}
            disabled={exportLoading}
          >
            {exportLoading ? "Preparing…" : `Download ${exportLabel}`}
          </Button>
        </div>
      )}

      <AgentTimeline outputs={session.agent_outputs} status={session.status} />

      {session.status === "complete" && session.report && <QualityMetricsCard session={session} />}

      {curated.length > 0 && (
        <div className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Activity
          </p>
          <ul className="space-y-2 text-xs text-argus-secondary">
            {curated.map((e, i) => (
              <li key={i} className="border-l-2 border-argus-border-moderate pl-2">
                <span className="font-medium text-argus-primary">
                  {formatPipelineStage(e.event)}
                </span>
                {e.detail ? <span className="mt-0.5 block text-argus-tertiary">{e.detail}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {loadError && (
        <p className="text-sm text-argus-warning" role="status">
          {loadError}
        </p>
      )}
    </aside>
  );
}
