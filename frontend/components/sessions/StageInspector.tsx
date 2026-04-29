"use client";

import { useEffect, useMemo } from "react";

import { useSelection } from "@/lib/SelectionContext";
import type { AgentOutput, SessionDetail } from "@/lib/types";

const STAGE_LABELS: Record<string, string> = {
  planner: "Planner",
  researcher: "Researcher",
  analyst: "Analyst",
  critic: "Critic",
  analyst_revision: "Analyst (revision)",
  critic_post_revision: "Critic (post-revision)",
  verifier: "Verifier",
  writer: "Writer",
};

const STAGE_DESCRIPTIONS: Record<string, string> = {
  planner: "Breaks the strategic question into research tasks with decision criteria and scope.",
  researcher: "Pulls evidence from documents and the web; deduplicates, triages, and scores.",
  analyst: "Synthesizes ≥6 key claims, each tied to evidence UUIDs.",
  critic: "Challenges the analysis; flags weak points; issues revision instructions.",
  analyst_revision: "Applies critic feedback and re-synthesizes.",
  verifier: "Re-checks every claim against the evidence catalog.",
  writer: "Produces the consulting-grade deliverable with executive insights and kill criteria.",
};

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

function tryParseJson(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function preview(value: unknown, limit = 4): string {
  if (value == null) return "";
  if (typeof value === "string") return value.slice(0, 600);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const head = value.slice(0, limit);
    return JSON.stringify(head, null, 2);
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2).slice(0, 1200);
  }
  return String(value);
}

export default function StageInspector({ session }: { session: SessionDetail }) {
  const { selectedStage, setSelectedStage } = useSelection();

  useEffect(() => {
    if (!selectedStage) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedStage(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedStage, setSelectedStage]);

  const out: AgentOutput | undefined = useMemo(() => {
    if (!selectedStage) return undefined;
    return (session.agent_outputs ?? []).find(
      (o) => (o.agent_name || "").toLowerCase() === selectedStage
    );
  }, [selectedStage, session.agent_outputs]);

  if (!selectedStage) return null;

  const label = STAGE_LABELS[selectedStage] ?? selectedStage;
  const description = STAGE_DESCRIPTIONS[selectedStage] ?? "";
  const parsed = out?.output ? tryParseJson(out.output) : null;

  return (
    <>
      <div
        aria-hidden
        onClick={() => setSelectedStage(null)}
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
      />
      <aside
        role="dialog"
        aria-label={`${label} stage details`}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col overflow-hidden border-l border-argus-border-subtle bg-canvas shadow-argus-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-argus-border-subtle px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-argus-tertiary">
              Pipeline stage
            </div>
            <h2 className="mt-1 font-serif text-lg text-argus-primary">{label}</h2>
            {description ? (
              <p className="mt-1 text-[12px] leading-snug text-argus-secondary">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => setSelectedStage(null)}
            className="rounded-argus-sm p-1 text-argus-tertiary transition-colors hover:bg-elevated hover:text-argus-primary"
            aria-label="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        {!out ? (
          <div className="flex-1 px-5 py-6 text-[13px] text-argus-tertiary">
            <p>This stage has no recorded output.</p>
            <p className="mt-1.5 text-[12px]">
              Either it didn&apos;t run for this session (e.g., a revision wasn&apos;t triggered), or the
              run is still in progress.
            </p>
          </div>
        ) : (
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4 text-[13px]">
            <dl className="grid grid-cols-2 gap-3 rounded-argus-md border border-argus-border-subtle bg-surface px-3 py-2.5">
              <div>
                <dt className="text-[10px] uppercase tracking-wide text-argus-tertiary">Duration</dt>
                <dd className="mt-0.5 font-mono text-[14px] text-argus-primary tabular-nums">
                  {out.duration_ms ? `${(out.duration_ms / 1000).toFixed(1)}s` : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide text-argus-tertiary">Tokens</dt>
                <dd className="mt-0.5 font-mono text-[14px] text-argus-primary tabular-nums">
                  {out.token_count ? out.token_count.toLocaleString() : "—"}
                </dd>
              </div>
            </dl>

            {out.input ? (
              <section>
                <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-argus-tertiary">
                  Input preview
                </h3>
                <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-argus-sm bg-elevated p-3 font-mono text-[11px] leading-relaxed text-argus-secondary">
                  {out.input.slice(0, 800)}
                </pre>
              </section>
            ) : null}

            <section>
              <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-argus-tertiary">
                Output
              </h3>
              {parsed ? (
                <pre className="max-h-[60vh] overflow-auto rounded-argus-sm bg-elevated p-3 font-mono text-[11px] leading-relaxed text-argus-secondary">
                  {preview(parsed)}
                </pre>
              ) : (
                <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-argus-sm bg-elevated p-3 font-mono text-[11px] leading-relaxed text-argus-secondary">
                  {out.output.slice(0, 4000)}
                </pre>
              )}
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
