"use client";

import { useMemo } from "react";

import { useSelection } from "@/lib/SelectionContext";
import type { AgentOutput, SessionDetail } from "@/lib/types";

const STAGE_ORDER: { id: string; label: string; short: string }[] = [
  { id: "planner", label: "Planner", short: "Plan" },
  { id: "researcher", label: "Researcher", short: "Research" },
  { id: "analyst", label: "Analyst", short: "Analyze" },
  { id: "critic", label: "Critic", short: "Critique" },
  { id: "analyst_revision", label: "Analyst (revision)", short: "Revise" },
  { id: "verifier", label: "Verifier", short: "Verify" },
  { id: "writer", label: "Writer", short: "Write" },
];

function fmtDuration(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`;
}

function fmtTokens(n: number): string {
  if (!n) return "";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function PipelineTimeline({
  session,
}: {
  session: SessionDetail;
}) {
  const { selectedStage, setSelectedStage } = useSelection();
  const outputs = session.agent_outputs ?? [];

  const stageMap = useMemo(() => {
    const m = new Map<string, AgentOutput>();
    for (const o of outputs) {
      const key = (o.agent_name || "").toLowerCase();
      // Last output wins so revisions overwrite originals if same key.
      m.set(key, o);
    }
    return m;
  }, [outputs]);

  // Aggregate totals.
  const { totalDuration, totalTokens, completeCount, totalCount } = useMemo(() => {
    let d = 0;
    let t = 0;
    let c = 0;
    let total = 0;
    for (const stage of STAGE_ORDER) {
      const out = stageMap.get(stage.id);
      // Skip optional analyst_revision from total count if absent.
      const isOptional = stage.id === "analyst_revision";
      if (!out && isOptional) continue;
      total++;
      if (out) {
        c++;
        d += out.duration_ms ?? 0;
        t += out.token_count ?? 0;
      }
    }
    return { totalDuration: d, totalTokens: t, completeCount: c, totalCount: total };
  }, [stageMap]);

  if (outputs.length === 0 && session.status !== "complete") {
    // Render a faint placeholder so the timeline keeps the layout slot reserved.
    return (
      <div className="mb-3 rounded-argus-md border border-dashed border-argus-border-subtle bg-surface/40 px-4 py-3 text-[11px] text-argus-tertiary">
        Pipeline timeline will appear once the run produces output.
      </div>
    );
  }

  return (
    <section
      aria-label="Pipeline timeline"
      className="mb-3 rounded-argus-md border border-argus-border-subtle bg-surface px-4 py-3 shadow-argus-sm"
    >
      <header className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Pipeline
          </span>
          <span className="text-[11px] text-argus-secondary tabular-nums">
            {completeCount}/{totalCount} stages
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-argus-tertiary">
          <span className="tabular-nums">{fmtDuration(totalDuration)}</span>
          <span className="text-argus-border-moderate">·</span>
          <span className="tabular-nums">{fmtTokens(totalTokens)} tokens</span>
        </div>
      </header>
      <ol className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-7">
        {STAGE_ORDER.map((stage) => {
          const out = stageMap.get(stage.id);
          const isComplete = !!out;
          const isSelected = selectedStage === stage.id;
          const isOptional = stage.id === "analyst_revision";
          const skipped = isOptional && !out;

          const baseTone = skipped
            ? "border-argus-border-subtle bg-canvas/50 text-argus-tertiary/60"
            : isComplete
              ? "border-argus-success-border bg-argus-success-subtle/40 text-argus-primary"
              : "border-argus-border-subtle bg-surface text-argus-tertiary";

          const ringTone = isSelected ? "ring-2 ring-argus-accent ring-offset-1 ring-offset-surface" : "";

          return (
            <li key={stage.id}>
              <button
                type="button"
                onClick={() =>
                  setSelectedStage(isSelected ? null : skipped ? null : stage.id)
                }
                disabled={skipped}
                className={`group relative flex w-full flex-col items-start rounded-argus-sm border px-2.5 py-2 text-left transition-all ${baseTone} ${ringTone} ${
                  skipped ? "cursor-not-allowed" : "hover:border-argus-accent/60 hover:bg-elevated"
                }`}
                title={
                  skipped
                    ? `${stage.label} — not run`
                    : isComplete
                      ? `${stage.label} · click for details`
                      : `${stage.label} — pending`
                }
              >
                <div className="flex w-full items-center gap-1.5">
                  <span
                    className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${
                      skipped
                        ? "bg-argus-neutral/40"
                        : isComplete
                          ? "bg-argus-success"
                          : "bg-argus-neutral"
                    }`}
                    aria-hidden
                  />
                  <span className="truncate text-[11px] font-medium leading-none">
                    {stage.short}
                  </span>
                </div>
                <div className="mt-1 flex w-full items-baseline gap-1.5 text-[10px] text-argus-tertiary">
                  <span className="tabular-nums">
                    {isComplete ? fmtDuration(out!.duration_ms) : skipped ? "—" : "·"}
                  </span>
                  <span className="ml-auto tabular-nums">
                    {isComplete && out!.token_count ? fmtTokens(out!.token_count) : ""}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
