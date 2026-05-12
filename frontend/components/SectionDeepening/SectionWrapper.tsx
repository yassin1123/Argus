"use client";

/**
 * SectionWrapper — Phase 2 / Week 9 / Day 2.
 *
 * Wraps one rendered memo section, attaches a hover-state "Deepen"
 * affordance in the top-right, and triggers the host's onDeepen
 * callback with the section's dotted path.
 *
 * Hard rule from spec: the recommendation never gets a Deepen
 * affordance. The :func:`isDeepenable` check in the host
 * orchestrator decides whether to render this wrapper at all
 * for a given section — here we just trust the path and render
 * the affordance.
 */

import { ReactNode, useState } from "react";

export interface SectionWrapperProps {
  sectionPath: string;
  /** Whether deepening is currently in-flight on this session. When
   * true the affordance is rendered disabled — one deepening at a
   * time, per W9/D2 hard rule. */
  inFlight: boolean;
  onDeepen: (sectionPath: string) => void;
  children: ReactNode;
}

export default function SectionWrapper({
  sectionPath,
  inFlight,
  onDeepen,
  children,
}: SectionWrapperProps) {
  const [hovering, setHovering] = useState(false);
  return (
    <div
      data-testid={`section-wrapper-${sectionPath}`}
      data-section-path={sectionPath}
      className="relative"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      {children}
      {hovering ? (
        <button
          type="button"
          data-testid={`deepen-affordance-${sectionPath}`}
          onClick={() => !inFlight && onDeepen(sectionPath)}
          disabled={inFlight}
          title={
            inFlight
              ? "Another deepening is in progress on this engagement. Wait for it to finish."
              : `Deepen ${sectionPath}`
          }
          className="absolute right-2 top-2 rounded border border-argus-firm-border bg-argus-firm-bg px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-argus-firm hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {inFlight ? "Deepening…" : "Deepen"}
        </button>
      ) : null}
    </div>
  );
}
