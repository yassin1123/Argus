"use client";

/**
 * Frameworks dispatcher — Phase 2 / Week 8 / Day 3.
 *
 * Receives the writer payload's optional ``frameworks`` slot and
 * dispatches each non-null sub-framework to its bespoke renderer.
 * Hides itself entirely when ``frameworks`` is null or all three
 * slots are null (preserves backward compat — legacy memos render
 * unchanged).
 *
 * Surface item from W8/D3 spec: existing MemoRenderer dispatch is
 * inline conditional JSX. This component keeps the per-framework
 * conditional logic OUT of MemoRenderer — the host just renders
 * <FrameworksSection /> and gets all three for free.
 */

import { isDeepenable } from "@/lib/api/sectionDeepening";
import SectionWrapper from "@/components/SectionDeepening/SectionWrapper";

import PortersFiveForces, { type PortersFiveForcesData } from "./PortersFiveForces";
import TwoByTwoMatrix, { type TwoByTwoMatrixData } from "./TwoByTwoMatrix";
import ValueChain, { type ValueChainData } from "./ValueChain";

export interface FrameworksData {
  two_by_two?: TwoByTwoMatrixData | null;
  porters_five_forces?: PortersFiveForcesData | null;
  value_chain?: ValueChainData | null;
}

/** W9/D2: optional deepening hook threaded through MemoRenderer. */
export interface FrameworksDeepeningHook {
  inFlight: boolean;
  onDeepen: (sectionPath: string) => void;
}

export interface FrameworksSectionProps {
  data?: FrameworksData | null;
  deepening?: FrameworksDeepeningHook;
}

function wrap(
  sectionPath: string,
  deepening: FrameworksDeepeningHook | undefined,
  content: JSX.Element,
): JSX.Element {
  if (!deepening || !isDeepenable(sectionPath)) return content;
  return (
    <SectionWrapper
      sectionPath={sectionPath}
      inFlight={deepening.inFlight}
      onDeepen={deepening.onDeepen}
    >
      {content}
    </SectionWrapper>
  );
}

export default function FrameworksSection({ data, deepening }: FrameworksSectionProps) {
  if (!data) return null;
  const { two_by_two, porters_five_forces, value_chain } = data;
  if (!two_by_two && !porters_five_forces && !value_chain) return null;

  return (
    <section data-testid="frameworks-section" className="mt-6 space-y-6">
      {two_by_two
        ? wrap("frameworks.two_by_two", deepening, <TwoByTwoMatrix data={two_by_two} />)
        : null}
      {porters_five_forces
        ? wrap(
            "frameworks.porters_five_forces",
            deepening,
            <PortersFiveForces data={porters_five_forces} />,
          )
        : null}
      {value_chain
        ? wrap("frameworks.value_chain", deepening, <ValueChain data={value_chain} />)
        : null}
    </section>
  );
}

export { default as TwoByTwoMatrix } from "./TwoByTwoMatrix";
export { default as PortersFiveForces } from "./PortersFiveForces";
export { default as ValueChain } from "./ValueChain";
export type { TwoByTwoMatrixData } from "./TwoByTwoMatrix";
export type { PortersFiveForcesData } from "./PortersFiveForces";
export type { ValueChainData } from "./ValueChain";
