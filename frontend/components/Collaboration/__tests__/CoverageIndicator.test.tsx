import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { CoverageMap } from "@/lib/api/collaboration";

import CoverageIndicator from "../CoverageIndicator";

function makeCoverage(overrides: Partial<CoverageMap> = {}): CoverageMap {
  return {
    session_id: "s1",
    entries: [
      { section_path: "summary",         assigned: true,  assigned_to: "u-1", assigned_by: "u-1", status: "done", assignment_id: "a1", updated_at: null },
      { section_path: "risks",           assigned: true,  assigned_to: "u-2", assigned_by: "u-1", status: "in_progress", assignment_id: "a2", updated_at: null },
      { section_path: "next_steps",      assigned: true,  assigned_to: "u-2", assigned_by: "u-1", status: "needs_review", assignment_id: "a3", updated_at: null },
      { section_path: "synergy_estimate", assigned: false, assigned_to: null, assigned_by: null, status: "not_started", assignment_id: null, updated_at: null },
      { section_path: "valuation_range",  assigned: false, assigned_to: null, assigned_by: null, status: "not_started", assignment_id: null, updated_at: null },
    ],
    unassigned_count: 2,
    by_status: { not_started: 2, in_progress: 1, needs_review: 1, done: 1 },
    ready_to_submit: false,
    ...overrides,
  };
}

describe("CoverageIndicator", () => {
  it("renders Loading… when coverage is null", () => {
    render(<CoverageIndicator coverage={null} />);
    expect(screen.getByTestId("coverage-indicator").textContent).toContain("Loading");
  });

  it("renders the rollup counts correctly", () => {
    render(<CoverageIndicator coverage={makeCoverage()} />);
    expect(screen.getByTestId("coverage-summary").textContent).toContain("3");
    expect(screen.getByTestId("coverage-summary").textContent).toContain("5");
    expect(screen.getByTestId("coverage-status-done").textContent).toContain("1");
    expect(screen.getByTestId("coverage-status-in_progress").textContent).toContain("1");
    expect(screen.getByTestId("coverage-unassigned-count").textContent).toContain("2 unassigned");
  });

  it("highlights unassigned in red when isLead=true", () => {
    const { rerender } = render(
      <CoverageIndicator coverage={makeCoverage()} isLead={false} />,
    );
    const muted = screen.getByTestId("coverage-unassigned-count")
      .getAttribute("style") || "";
    rerender(<CoverageIndicator coverage={makeCoverage()} isLead />);
    const highlighted = screen.getByTestId("coverage-unassigned-count")
      .getAttribute("style") || "";
    expect(muted).not.toEqual(highlighted);
  });

  it("renders the ready-to-submit pill when flag is true", () => {
    render(
      <CoverageIndicator
        coverage={makeCoverage({
          unassigned_count: 0,
          by_status: { not_started: 0, in_progress: 0, needs_review: 0, done: 5 },
          ready_to_submit: true,
        })}
      />,
    );
    expect(screen.getByTestId("coverage-ready-to-submit")).toBeInTheDocument();
  });
});
