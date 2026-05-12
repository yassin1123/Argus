"use client";

/**
 * DeepenOrchestrator — Phase 2 / Week 9 / Day 2.
 *
 * Top-level host for the W9 deepening UI. Renders the history
 * sidebar, owns the modal-vs-panel state, enforces the
 * "one-deepening-at-a-time" rule, and exposes a children
 * render-prop so the memo can attach section affordances via
 * :class:`SectionWrapper` without each component re-implementing
 * the orchestration.
 *
 * Usage::
 *
 *     <DeepenOrchestrator sessionId={sid}>
 *       {({ inFlight, onDeepen }) => (
 *         <MemoRenderer
 *           payload={p}
 *           modeName={mode}
 *           deepening={{ inFlight, onDeepen }}
 *         />
 *       )}
 *     </DeepenOrchestrator>
 */

import { ReactNode, useState } from "react";

import { DeepeningDetail } from "@/lib/api/sectionDeepening";

import DeepeningHistory from "./DeepeningHistory";
import StatusPanel from "./StatusPanel";
import TriggerModal from "./TriggerModal";

export interface DeepenHook {
  inFlight: boolean;
  onDeepen: (sectionPath: string) => void;
}

export interface DeepenOrchestratorProps {
  sessionId: string;
  children: (hook: DeepenHook) => ReactNode;
}

type Mode =
  | { kind: "idle" }
  | { kind: "trigger"; sectionPath: string }
  | { kind: "status"; deepeningId: string; sectionPath: string }
  | { kind: "result"; detail: DeepeningDetail };

export default function DeepenOrchestrator({
  sessionId,
  children,
}: DeepenOrchestratorProps) {
  const [mode, setMode] = useState<Mode>({ kind: "idle" });
  const [reloadKey, setReloadKey] = useState(0);

  const inFlight =
    mode.kind === "trigger" || mode.kind === "status";

  const onDeepen = (sectionPath: string) => {
    if (inFlight) return; // hard rule: one at a time
    setMode({ kind: "trigger", sectionPath });
  };

  return (
    <div data-testid="deepen-orchestrator" data-in-flight={inFlight}>
      <DeepeningHistory
        sessionId={sessionId}
        reloadKey={reloadKey}
        onOpenDeepening={(deepeningId, sectionPath) =>
          setMode({ kind: "status", deepeningId, sectionPath })
        }
      />

      {children({ inFlight, onDeepen })}

      {mode.kind === "trigger" ? (
        <TriggerModal
          sessionId={sessionId}
          sectionPath={mode.sectionPath}
          onCancel={() => setMode({ kind: "idle" })}
          onTriggered={(deepeningId, sectionPath) => {
            setReloadKey((k) => k + 1);
            setMode({ kind: "status", deepeningId, sectionPath });
          }}
        />
      ) : null}

      {mode.kind === "status" ? (
        <StatusPanel
          sessionId={sessionId}
          deepeningId={mode.deepeningId}
          sectionPath={mode.sectionPath}
          onClose={() => {
            setReloadKey((k) => k + 1);
            setMode({ kind: "idle" });
          }}
          onTerminal={(detail) => {
            setReloadKey((k) => k + 1);
            if (detail.status === "complete") {
              setMode({ kind: "result", detail });
            }
            // For "failed", leave the StatusPanel open so the
            // consultant can read the failure_reason before
            // closing.
          }}
        />
      ) : null}

      {mode.kind === "result" ? (
        <DeepeningResultPreview
          detail={mode.detail}
          onClose={() => setMode({ kind: "idle" })}
        />
      ) : null}
    </div>
  );
}

/**
 * Day 2 placeholder for Day 3's diff panel — just a labeled JSON
 * preview so the consultant can confirm the deepening landed.
 */
function DeepeningResultPreview({
  detail,
  onClose,
}: {
  detail: DeepeningDetail;
  onClose: () => void;
}) {
  return (
    <div
      data-testid="result-preview"
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="w-[720px] max-w-[92vw] rounded-md border border-argus-border-subtle bg-surface p-5 shadow-lg">
        <header className="mb-3 flex items-baseline justify-between">
          <h3 className="font-serif text-[16px] font-semibold text-argus-primary">
            Deepened section: {detail.section_path}
          </h3>
          <span className="font-mono text-[10px] text-argus-tertiary">
            Day 3 will turn this into a diff panel
          </span>
        </header>
        <pre
          data-testid="result-json"
          className="max-h-[60vh] overflow-auto rounded border border-argus-border-subtle bg-elevated p-3 text-[11px] text-argus-primary"
        >
          {JSON.stringify(detail.deepened_section_json, null, 2)}
        </pre>
        <div className="mt-3 flex items-center justify-end">
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
