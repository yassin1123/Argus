"use client";

import type { AgentOutput } from "@/lib/types";

const ORDER = [
  "planner",
  "researcher",
  "analyst",
  "critic",
  "analyst_revision",
  "critic_post_revision",
  "verifier",
  "writer",
] as const;

const AGENT_LABELS: Record<string, string> = {
  planner: "Planning research",
  researcher: "Gathering evidence",
  analyst: "Building analysis",
  critic: "Stress test — first draft",
  analyst_revision: "Revising",
  critic_post_revision: "Stress test — after revision",
  verifier: "Verifying claims",
  verifier_retry: "Verifying claims",
  writer: "Writing report",
};

/** Hover hints for steps that look like duplicates but are intentional passes. */
const ROW_HINTS: Partial<Record<(typeof ORDER)[number], string>> = {
  critic: "Challenges the initial analysis. A second stress test runs later on the revised version.",
  critic_post_revision: "Same kind of challenge as above, but on the analyst’s updated draft — expected, not a loop.",
};

function stepComplete(agent: string, completed: Set<string>): boolean {
  if (agent === "verifier") return completed.has("verifier") || completed.has("verifier_retry");
  return completed.has(agent);
}

function rowForAgent(agent: string, byAgent: Map<string, AgentOutput>): AgentOutput | undefined {
  if (agent === "verifier") return byAgent.get("verifier") ?? byAgent.get("verifier_retry");
  return byAgent.get(agent);
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M20 6L9 17l-5-5"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function AgentTimeline({
  outputs,
  status,
}: {
  outputs: AgentOutput[];
  status: string;
}) {
  const byAgent = new Map(outputs.map((o) => [o.agent_name, o]));
  const completed = new Set(outputs.map((o) => o.agent_name));

  let currentIndex = ORDER.findIndex((a) => !stepComplete(a, completed));
  if (currentIndex < 0) currentIndex = ORDER.length;

  const maxMs = Math.max(
    1,
    ...ORDER.map((a) => rowForAgent(a, byAgent)?.duration_ms ?? 0),
  );

  return (
    <div
      className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm"
      aria-live="polite"
    >
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
        Pipeline
      </p>
      <ul className="space-y-0">
        {ORDER.map((agent, index) => {
          const isComplete = stepComplete(agent, completed);
          const isActive = index === currentIndex && status === "processing";
          const isPending = !isComplete && !isActive;
          const row = rowForAgent(agent, byAgent);
          const label = AGENT_LABELS[agent] ?? agent.replace(/_/g, " ");
          const duration = row?.duration_ms;

          return (
            <li
              key={agent}
              className="flex items-center gap-3 py-2"
              title={ROW_HINTS[agent]}
            >
              <div className="relative flex h-5 w-5 shrink-0 items-center justify-center">
                {isComplete && (
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-argus-success-subtle">
                    <CheckIcon className="text-argus-success" />
                  </div>
                )}
                {isActive && (
                  <div className="h-2.5 w-2.5 animate-pulse rounded-full bg-argus-accent" />
                )}
                {isPending && (
                  <div className="h-2 w-2 rounded-full border border-argus-border-moderate" />
                )}
              </div>
              <span
                className={`text-xs transition-colors duration-200 ${
                  isComplete
                    ? "font-medium text-argus-success"
                    : isActive
                      ? "font-semibold text-argus-primary"
                      : "text-argus-tertiary"
                }`}
              >
                {label}
              </span>
              {isComplete && duration != null && duration >= 0 && (
                <div className="ml-auto flex w-[5.5rem] flex-col items-end gap-0.5">
                  <div className="h-1 w-full overflow-hidden rounded-full bg-argus-border-subtle">
                    <div
                      className="h-1 rounded-full bg-argus-success"
                      style={{ width: `${Math.min(100, (duration / maxMs) * 100)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-argus-tertiary">{(duration / 1000).toFixed(1)}s</span>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {status === "failed" && (
        <p className="mt-3 text-sm text-argus-danger">Pipeline failed — check server logs.</p>
      )}
      {status === "insufficient" && (
        <p className="mt-3 text-sm text-argus-warning">
          Stopped at a quality gate — see the gap report in the answer column.
        </p>
      )}
    </div>
  );
}
