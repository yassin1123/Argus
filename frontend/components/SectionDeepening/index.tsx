"use client";

/**
 * SectionDeepening — Phase 2 / Week 9 / Day 2 entry point.
 *
 * Public surface:
 *   - DeepenOrchestrator: top-level host that manages modal /
 *     status panel / history / in-flight state.
 *   - SectionWrapper: per-section hover affordance.
 *   - Plus underlying TriggerModal / StatusPanel / DeepeningHistory
 *     for tests + direct embedding.
 */

export { default as DeepenOrchestrator } from "./DeepenOrchestrator";
export type { DeepenHook, DeepenOrchestratorProps } from "./DeepenOrchestrator";

export { default as SectionWrapper } from "./SectionWrapper";
export type { SectionWrapperProps } from "./SectionWrapper";

export { default as TriggerModal } from "./TriggerModal";
export type { TriggerModalProps } from "./TriggerModal";

export { default as StatusPanel } from "./StatusPanel";
export type { StatusPanelProps } from "./StatusPanel";

export { default as DeepeningHistory } from "./DeepeningHistory";
export type { DeepeningHistoryProps } from "./DeepeningHistory";
