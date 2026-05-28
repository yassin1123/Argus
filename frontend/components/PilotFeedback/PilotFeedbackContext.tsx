"use client";

// Optional pilot-feedback context — Phase 5 / Week 24 / Day 3.
// Carries the sessionId so per-claim feedback affordances inside the
// MemoRenderer can post without threading sessionId through every
// nested section. Absent context → affordances hide (exactly like the
// comments affordance), so the renderer stays usable outside a session.

import { createContext, useContext, type ReactNode } from "react";

interface PilotFeedbackCtx {
  sessionId: string;
}

const Ctx = createContext<PilotFeedbackCtx | null>(null);

export function PilotFeedbackProvider({
  sessionId,
  children,
}: {
  sessionId: string;
  children: ReactNode;
}) {
  return <Ctx.Provider value={{ sessionId }}>{children}</Ctx.Provider>;
}

export function usePilotFeedbackOptional(): PilotFeedbackCtx | null {
  return useContext(Ctx);
}
