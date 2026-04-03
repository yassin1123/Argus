"use client";

import { useEffect, useState } from "react";
import type { SessionDetail } from "@/lib/types";
import { formatPipelineStage } from "@/lib/formatters";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type PipelineEv = {
  stage?: string;
  event_type?: string;
  payload?: Record<string, unknown> | string | null;
};

export function ProcessingCenter({ session }: { session: SessionDetail }) {
  const [liveTail, setLiveTail] = useState<PipelineEv[]>([]);

  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/api/workspaces/${session.id}/events`);
      es.onmessage = (ev) => {
        try {
          const row = JSON.parse(ev.data) as PipelineEv;
          setLiveTail((prev) => [...prev, row].slice(-15));
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
      };
    } catch {
      /* SSE unavailable */
    }
    return () => es?.close();
  }, [session.id]);

  const trace = session.metadata?.pipeline_trace;
  const traceLines = Array.isArray(trace) ? trace.slice(-3) : [];
  const payloadDetail = (p: PipelineEv["payload"]): string => {
    if (p && typeof p === "object" && "detail" in p) return String((p as Record<string, unknown>).detail || "");
    return "";
  };
  const mergedActivity = liveTail
    .filter((e) => e.event_type === "trace" || (e.stage && e.stage.length > 0))
    .slice(-5)
    .map((e) => ({
      label: formatPipelineStage(e.stage || e.event_type || ""),
      detail: payloadDetail(e.payload),
    }));

  const headline = formatPipelineStage(session.pipeline_state);
  const outputs = session.agent_outputs ?? [];
  const lastComplete = [...outputs].reverse().find((o) => (o.duration_ms ?? 0) > 0);
  const elapsedHint =
    outputs.length > 0
      ? `Latest stage: ${outputs[outputs.length - 1]?.agent_name?.replace(/_/g, " ") ?? "—"}`
      : null;

  return (
    <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
      <div className="flex w-6 items-center justify-center gap-1" aria-hidden>
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-tertiary [animation-delay:0ms]" />
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-tertiary [animation-delay:200ms]" />
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-argus-tertiary [animation-delay:400ms]" />
      </div>
      <p className="mt-6 text-lg font-semibold text-argus-primary">{headline}</p>
      <p className="mt-2 text-sm text-argus-secondary">Researching and reasoning…</p>
      {elapsedHint ? <p className="mt-1 text-xs text-argus-tertiary">{elapsedHint}</p> : null}
      {lastComplete && (lastComplete.duration_ms ?? 0) > 0 ? (
        <p className="mt-1 text-[11px] text-argus-tertiary">
          Last completed step: {(lastComplete.duration_ms! / 1000).toFixed(1)}s
        </p>
      ) : null}

      {(traceLines.length > 0 || mergedActivity.length > 0) && (
        <div className="mt-8 w-full max-w-md rounded-[14px] border border-argus-border-subtle bg-surface p-4 text-left shadow-argus-sm">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-argus-tertiary">
            Recent activity
          </p>
          <ul className="mt-3 space-y-2 text-xs text-argus-secondary">
            {mergedActivity.length > 0
              ? mergedActivity.map((a, i) => (
                  <li key={`live-${i}`} className="border-l-2 border-argus-accent pl-2">
                    <span className="font-medium text-argus-primary">{a.label}</span>
                    {a.detail ? <span className="mt-0.5 block text-argus-tertiary">{a.detail}</span> : null}
                  </li>
                ))
              : traceLines.map((e, i) => (
                  <li key={i} className="border-l-2 border-argus-border-moderate pl-2">
                    <span className="font-medium text-argus-primary">
                      {formatPipelineStage(e.event)}
                    </span>
                    {e.detail ? (
                      <span className="mt-0.5 block text-argus-tertiary">{e.detail}</span>
                    ) : null}
                  </li>
                ))}
          </ul>
        </div>
      )}

      <p className="mt-6 max-w-xs text-xs text-argus-tertiary">
        Full step list and timings are in <strong className="text-argus-secondary">Pipeline</strong> on the
        right.
      </p>
    </div>
  );
}
