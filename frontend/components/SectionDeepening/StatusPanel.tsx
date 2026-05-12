"use client";

/**
 * StatusPanel — Phase 2 / Week 9 / Day 2.
 *
 * Polls the deepening row every 3s once a trigger fires. Shows a
 * 4-step pipeline (Retrieving → Analyzing → Rewriting → Done) and
 * live wall + cost counters. On ``complete`` reveals a "View result"
 * button that the host wires to Day 3's diff panel; for D2 the host
 * can pop a basic JSON preview.
 *
 * The component is purely presentational — the polling lifecycle
 * lives here but the host owns the modal-vs-status state.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  DeepeningDetail,
  DeepeningStatus,
  pollDeepening,
  sectionDisplayName,
} from "@/lib/api/sectionDeepening";

export interface StatusPanelProps {
  sessionId: string;
  deepeningId: string;
  sectionPath: string;
  /** Called when the deepening reaches a terminal state (``complete`` or ``failed``). */
  onTerminal?: (detail: DeepeningDetail) => void;
  /** Called when the consultant explicitly closes the panel. */
  onClose: () => void;
  /** Optional override for the polling interval. Default 3000 ms per spec. */
  pollIntervalMs?: number;
}

const STEPS: { key: string; label: string }[] = [
  { key: "retrieving", label: "Retrieving new evidence" },
  { key: "analyzing", label: "Analyzing" },
  { key: "rewriting", label: "Rewriting" },
  { key: "done", label: "Done" },
];

/** Coarse mapping of backend status → which step is active. */
function activeStepIndex(status: DeepeningStatus, chunks: number): number {
  if (status === "queued") return 0;
  if (status === "running") {
    // No fine-grained stage signal from the backend yet — chunks
    // having landed means we're past retrieval; otherwise still
    // retrieving. Day 3+ could emit progress events.
    return chunks > 0 ? 2 : 1;
  }
  if (status === "complete" || status === "failed") return 3;
  return 0;
}

export default function StatusPanel({
  sessionId,
  deepeningId,
  sectionPath,
  onTerminal,
  onClose,
  pollIntervalMs = 3000,
}: StatusPanelProps) {
  const [detail, setDetail] = useState<DeepeningDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stopped = useRef(false);
  const terminalFired = useRef(false);

  const tick = useCallback(async () => {
    if (stopped.current) return;
    try {
      const d = await pollDeepening(sessionId, deepeningId);
      if (stopped.current) return;
      setDetail(d);
      if ((d.status === "complete" || d.status === "failed") && !terminalFired.current) {
        terminalFired.current = true;
        stopped.current = true;
        onTerminal?.(d);
      }
    } catch (e) {
      if (stopped.current) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sessionId, deepeningId, onTerminal]);

  useEffect(() => {
    void tick();
    const id = setInterval(tick, pollIntervalMs);
    return () => {
      stopped.current = true;
      clearInterval(id);
    };
  }, [tick, pollIntervalMs]);

  const status: DeepeningStatus = detail?.status ?? "queued";
  const stepIdx = activeStepIndex(status, detail?.new_evidence_chunks_used ?? 0);
  const display = sectionDisplayName(sectionPath);

  return (
    <div
      data-testid="status-panel"
      data-status={status}
      role="dialog"
      aria-modal="true"
      aria-labelledby="status-panel-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="w-[520px] max-w-[92vw] rounded-md border border-argus-border-subtle bg-surface p-5 shadow-lg">
        <header className="mb-3">
          <h3
            id="status-panel-title"
            className="font-serif text-[18px] font-semibold text-argus-primary"
          >
            Deepening {display} —{" "}
            <span
              data-testid="status-label"
              className={
                status === "complete"
                  ? "text-argus-firm"
                  : status === "failed"
                  ? "text-argus-contested"
                  : "text-argus-secondary"
              }
            >
              {status === "queued"
                ? "Queued"
                : status === "running"
                ? "Running"
                : status === "complete"
                ? "Complete"
                : "Failed"}
            </span>
          </h3>
        </header>

        <ol data-testid="progress-steps" className="space-y-2">
          {STEPS.map((step, i) => {
            const state =
              i < stepIdx
                ? "done"
                : i === stepIdx
                ? status === "failed"
                  ? "failed"
                  : "active"
                : "pending";
            return (
              <li
                key={step.key}
                data-testid={`step-${step.key}`}
                data-state={state}
                className={`flex items-center gap-2 text-[12px] ${
                  state === "done"
                    ? "text-argus-firm"
                    : state === "active"
                    ? "text-argus-primary"
                    : state === "failed"
                    ? "text-argus-contested"
                    : "text-argus-tertiary"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`inline-block h-2 w-2 rounded-full ${
                    state === "done"
                      ? "bg-argus-firm"
                      : state === "active"
                      ? "bg-argus-secondary"
                      : state === "failed"
                      ? "bg-argus-contested"
                      : "bg-argus-tertiary"
                  }`}
                />
                {step.label}
              </li>
            );
          })}
        </ol>

        <div className="mt-4 flex items-center justify-between text-[11px] text-argus-tertiary">
          <span data-testid="wall-counter">
            Wall: {(detail?.wall_seconds ?? 0).toFixed(1)}s
          </span>
          <span data-testid="cost-counter">
            Cost: ${(detail?.cost_usd ?? 0).toFixed(2)}
          </span>
          <span data-testid="chunks-counter">
            New chunks: {detail?.new_evidence_chunks_used ?? 0}
          </span>
        </div>

        {error ? (
          <p data-testid="status-error" className="mt-2 text-[12px] text-argus-contested">
            Polling error: {error}
          </p>
        ) : null}

        {status === "failed" && detail?.failure_reason ? (
          <p
            data-testid="failure-reason"
            className="mt-3 rounded border border-argus-contested-border bg-argus-contested-bg p-2 text-[12px] text-argus-contested"
          >
            {detail.failure_reason}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          {status === "complete" ? (
            <button
              type="button"
              data-testid="view-result"
              onClick={() => detail && onTerminal?.(detail)}
              className="rounded border border-argus-firm-border bg-argus-firm-bg px-3 py-1.5 text-[12px] font-semibold text-argus-firm hover:opacity-90"
            >
              View result
            </button>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-argus-border-subtle bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:bg-elevated"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
