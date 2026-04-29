"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SessionDetail } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Approximate USD per 1M tokens (gpt-4o-ish blended in/out). Used only for the
// live cost meter; precise billing would need per-stage model lookup.
const COST_PER_1M_TOKENS_USD = 5.0;

type StageId =
  | "planner"
  | "researcher"
  | "analyst"
  | "critic"
  | "analyst_revision"
  | "verifier"
  | "writer";

const STAGES: { id: StageId; label: string; description: string }[] = [
  { id: "planner", label: "Planner", description: "Breaks question into research tasks" },
  { id: "researcher", label: "Researcher", description: "Pulls evidence from documents and web" },
  { id: "analyst", label: "Analyst", description: "Synthesizes claims and trade-offs" },
  { id: "critic", label: "Critic", description: "Challenges analysis and asks for revisions" },
  { id: "analyst_revision", label: "Analyst (revision)", description: "Applies critic feedback" },
  { id: "verifier", label: "Verifier", description: "Re-checks every claim against evidence" },
  { id: "writer", label: "Writer", description: "Produces consulting-grade deliverable" },
];

type PipelineEv = {
  id?: number;
  stage?: string;
  status?: string;
  event_type?: string;
  duration_ms?: number | null;
  token_in?: number | null;
  token_out?: number | null;
  created_at?: string | null;
  payload?: Record<string, unknown> | null;
};

type StageState = {
  status: "pending" | "active" | "complete" | "failed";
  duration_ms?: number;
  narration?: string;
  startedAt?: number;
};

function p(payload: PipelineEv["payload"]): Record<string, unknown> {
  return payload && typeof payload === "object" ? payload : {};
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

function narrate(ev: PipelineEv): string {
  const stage = ev.stage || "";
  const status = ev.status || "";
  const pl = p(ev.payload);
  const message = typeof pl.message === "string" ? pl.message : "";

  if (stage === "planner") {
    if (status === "started") return "Breaking down the strategic question into research tasks…";
    if (status === "completed") {
      const t = num(pl.tasks);
      const b = num(pl.branches);
      if (t && b) return `Generated ${t} tasks across ${b} research branches.`;
      return "Research plan ready.";
    }
  }
  if (stage === "researcher") {
    if (status === "started") return message || "Executing research tasks…";
    if (status === "progress") {
      const branch = String(pl.branch ?? "");
      const queries = num(pl.queries_completed);
      const evidence = num(pl.evidence_collected);
      if (branch && queries !== null && evidence !== null) {
        return `Branch "${branch}": ${queries} queries · ${evidence} evidence object${evidence === 1 ? "" : "s"} collected.`;
      }
    }
    if (status === "completed") {
      const e = num(pl.evidence_objects);
      const s = num(pl.sources);
      if (e !== null && s !== null) return `Collected ${e} evidence objects from ${s} sources.`;
    }
  }
  if (stage === "analyst" || stage === "analyst_revision") {
    if (status === "started") {
      return stage === "analyst_revision" ? "Applying critic feedback…" : "Synthesizing key claims…";
    }
    if (status === "completed") {
      const c = num(pl.key_claims);
      if (c !== null) return `Synthesized ${c} key claims.`;
    }
  }
  if (stage === "critic") {
    if (status === "started") return "Challenging the analysis…";
    if (status === "completed") {
      const verdict = String(pl.verdict ?? "");
      const revisions = num(pl.revisions);
      if (verdict === "accept") return "Critic accepted the analysis.";
      if (verdict === "revise" && revisions !== null) {
        return `Critic flagged ${revisions} revision${revisions === 1 ? "" : "s"}.`;
      }
    }
  }
  if (stage === "verifier") {
    if (status === "started") return "Re-checking every claim against the evidence catalog…";
    if (status === "completed") {
      const sup = num(pl.supported);
      const weak = num(pl.weak);
      const un = num(pl.unsupported);
      if (sup !== null && weak !== null && un !== null) {
        return `${sup} supported · ${weak} weak · ${un} unsupported.`;
      }
    }
  }
  if (stage === "writer") {
    if (status === "started") return "Producing consulting-grade deliverable…";
    if (status === "completed") return "Report ready.";
  }
  if (stage === "pipeline" && status === "complete") return "Pipeline complete.";

  return message || "";
}

function fmtDuration(ms: number | null | undefined): string {
  if (!ms || ms < 0) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function fmtCost(tokens: number): string {
  const usd = (tokens / 1_000_000) * COST_PER_1M_TOKENS_USD;
  if (usd < 0.01) return "<$0.01";
  return `$${usd.toFixed(2)}`;
}

function StageRow({
  stage,
  state,
}: {
  stage: { id: StageId; label: string; description: string };
  state: StageState;
}) {
  const dotClass =
    state.status === "complete"
      ? "bg-argus-success"
      : state.status === "active"
        ? "bg-argus-accent animate-pulse"
        : state.status === "failed"
          ? "bg-argus-danger"
          : "bg-argus-neutral/50";
  const labelClass =
    state.status === "active"
      ? "text-argus-primary"
      : state.status === "complete" || state.status === "failed"
        ? "text-argus-secondary"
        : "text-argus-tertiary";
  return (
    <li className="flex items-start gap-3 py-2">
      <span
        className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${dotClass}`}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <span className={`text-[13px] font-medium ${labelClass}`}>{stage.label}</span>
          <span className="text-[11px] text-argus-tertiary tabular-nums">
            {state.status === "complete" ? fmtDuration(state.duration_ms) : ""}
            {state.status === "active" ? "running…" : ""}
          </span>
        </div>
        {state.narration ? (
          <p className="mt-0.5 line-clamp-2 text-[11px] text-argus-tertiary">{state.narration}</p>
        ) : state.status === "pending" ? (
          <p className="mt-0.5 text-[11px] text-argus-tertiary/70">{stage.description}</p>
        ) : null}
      </div>
    </li>
  );
}

export function ProcessingCenter({ session }: { session: SessionDetail }) {
  const [events, setEvents] = useState<PipelineEv[]>([]);
  const [tokensTotal, setTokensTotal] = useState<number>(0);
  const [startedAt] = useState<number>(() => Date.now());
  const [now, setNow] = useState<number>(() => Date.now());
  const lastEventIdRef = useRef<number>(0);

  // Tick every second for the elapsed-time clock.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // SSE — append events as they arrive and tally token usage.
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/api/workspaces/${session.id}/events`);
      es.onmessage = (msg) => {
        try {
          const row = JSON.parse(msg.data) as PipelineEv;
          if (typeof row.id === "number" && row.id <= lastEventIdRef.current) return;
          if (typeof row.id === "number") lastEventIdRef.current = row.id;
          setEvents((prev) => [...prev, row].slice(-200));
          const ti = num(row.token_in);
          const to = num(row.token_out);
          if (ti !== null || to !== null) {
            setTokensTotal((prev) => prev + (ti ?? 0) + (to ?? 0));
          }
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
      };
    } catch {
      /* SSE unavailable — agent_outputs fallback below still works */
    }
    return () => es?.close();
  }, [session.id]);

  // Build per-stage state by reducing over events. Events that lack token usage
  // are still useful for status/narration; agent_outputs is used as a fallback
  // for the token tally if SSE never delivered them.
  const stageStates = useMemo<Record<StageId, StageState>>(() => {
    const init: Record<StageId, StageState> = {
      planner: { status: "pending" },
      researcher: { status: "pending" },
      analyst: { status: "pending" },
      critic: { status: "pending" },
      analyst_revision: { status: "pending" },
      verifier: { status: "pending" },
      writer: { status: "pending" },
    };
    for (const ev of events) {
      const stage = (ev.stage || "") as StageId;
      if (!(stage in init)) continue;
      const status = ev.status || "";
      if (status === "started" || status === "progress") {
        init[stage] = {
          ...init[stage],
          status: "active",
          narration: narrate(ev) || init[stage].narration,
        };
      } else if (status === "completed") {
        init[stage] = {
          status: "complete",
          duration_ms: ev.duration_ms ?? init[stage].duration_ms,
          narration: narrate(ev) || init[stage].narration,
        };
      } else if (status === "failed" || ev.event_type === "error") {
        init[stage] = { status: "failed", narration: narrate(ev) };
      }
    }
    return init;
  }, [events]);

  // Token fallback from agent_outputs (covers cold-load: page opened mid-run).
  const tokensFromOutputs = useMemo(() => {
    return (session.agent_outputs ?? []).reduce(
      (acc, o) => acc + (typeof o.token_count === "number" ? o.token_count : 0),
      0
    );
  }, [session.agent_outputs]);

  const tokens = Math.max(tokensTotal, tokensFromOutputs);
  const elapsedSec = Math.max(0, Math.round((now - startedAt) / 1000));
  const elapsedLabel = `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, "0")}`;

  // Active stage narration → headline.
  const activeStage = (Object.keys(stageStates) as StageId[]).find(
    (k) => stageStates[k].status === "active"
  );
  const headlineNarration = activeStage
    ? stageStates[activeStage].narration ||
      STAGES.find((s) => s.id === activeStage)?.description ||
      "Working…"
    : events.length > 0
      ? narrate(events[events.length - 1]) || "Working…"
      : "Starting analysis…";

  return (
    <div className="flex flex-col items-center px-4 py-10">
      <div className="flex w-6 items-center justify-center gap-1" aria-hidden>
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-tertiary [animation-delay:0ms]" />
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-tertiary [animation-delay:200ms]" />
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-tertiary [animation-delay:400ms]" />
      </div>
      <p className="mt-5 max-w-md text-center text-[15px] font-medium text-argus-primary">
        {headlineNarration}
      </p>

      {/* Live counters */}
      <div className="mt-6 grid w-full max-w-lg grid-cols-3 gap-2">
        <div className="rounded-argus-md border border-argus-border-subtle bg-surface px-3 py-2 text-center">
          <div className="text-[10px] uppercase tracking-wider text-argus-tertiary">Elapsed</div>
          <div className="mt-1 font-mono text-base text-argus-primary tabular-nums">
            {elapsedLabel}
          </div>
        </div>
        <div className="rounded-argus-md border border-argus-border-subtle bg-surface px-3 py-2 text-center">
          <div className="text-[10px] uppercase tracking-wider text-argus-tertiary">Tokens</div>
          <div className="mt-1 font-mono text-base text-argus-primary tabular-nums">
            {fmtTokens(tokens)}
          </div>
        </div>
        <div className="rounded-argus-md border border-argus-border-subtle bg-surface px-3 py-2 text-center">
          <div className="text-[10px] uppercase tracking-wider text-argus-tertiary">Est. cost</div>
          <div className="mt-1 font-mono text-base text-argus-primary tabular-nums">
            {fmtCost(tokens)}
          </div>
        </div>
      </div>

      {/* Stage timeline */}
      <div className="mt-6 w-full max-w-lg rounded-argus-md border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-argus-tertiary">
          Pipeline progress
        </p>
        <ul className="divide-y divide-argus-border-subtle">
          {STAGES.map((stage) => (
            <StageRow key={stage.id} stage={stage} state={stageStates[stage.id]} />
          ))}
        </ul>
      </div>

      <p className="mt-5 max-w-sm text-center text-[11px] text-argus-tertiary">
        Cost is an estimate ({COST_PER_1M_TOKENS_USD.toFixed(2)} USD per 1M tokens, blended) — see
        the audit panel for per-stage tokens after the run.
      </p>
    </div>
  );
}
