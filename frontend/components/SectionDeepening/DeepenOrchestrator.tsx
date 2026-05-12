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
import DiffPanel from "./DiffPanel";
import StatusPanel from "./StatusPanel";
import TriggerModal from "./TriggerModal";

export interface DeepenHook {
  inFlight: boolean;
  onDeepen: (sectionPath: string) => void;
}

export interface DeepenOrchestratorProps {
  sessionId: string;
  children: (hook: DeepenHook) => ReactNode;
  /** W9/D3: called after a successful accept lands. The host
   * should re-fetch the session report to pick up the merged
   * section. Optional — if absent, the orchestrator still closes
   * the diff panel cleanly. */
  onPayloadUpdated?: (newPayload: Record<string, unknown>) => void;
}

type Mode =
  | { kind: "idle" }
  | { kind: "trigger"; sectionPath: string }
  | { kind: "status"; deepeningId: string; sectionPath: string }
  | { kind: "result"; detail: DeepeningDetail };

export default function DeepenOrchestrator({
  sessionId,
  children,
  onPayloadUpdated,
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
        <DiffPanel
          sessionId={sessionId}
          detail={mode.detail}
          onAccepted={(newPayload) => {
            setReloadKey((k) => k + 1);
            if (onPayloadUpdated) {
              onPayloadUpdated(newPayload);
            }
            setMode({ kind: "idle" });
          }}
          onRejected={() => {
            setReloadKey((k) => k + 1);
            setMode({ kind: "idle" });
          }}
          onClose={() => setMode({ kind: "idle" })}
        />
      ) : null}
    </div>
  );
}
