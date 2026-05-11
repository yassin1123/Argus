import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import TwoByTwoMatrix, { type TwoByTwoMatrixData } from "../TwoByTwoMatrix";

const SAMPLE: TwoByTwoMatrixData = {
  title: "Acquisition target screen — segments",
  x_axis_label: "Strategic fit",
  x_axis_low_label: "Low",
  x_axis_high_label: "High",
  y_axis_label: "Ease of integration",
  y_axis_low_label: "Low",
  y_axis_high_label: "High",
  items: [
    {
      name: "Facilities Maintenance",
      quadrant: "top_right",
      rationale: "Strong strategic fit; low cultural distance; shared customer base.",
      evidence_citations: ["c-fm-1", "c-fm-2"],
    },
    {
      name: "Mechanical Services",
      quadrant: "bottom_left",
      rationale: "Weak fit, hard integration: separate sales motion + legacy ERP.",
      evidence_citations: ["c-ms-1"],
    },
    {
      name: "Compliance",
      quadrant: "top_left",
      rationale: "Hard to integrate culturally despite strong synergy potential.",
      evidence_citations: ["c-co-1"],
    },
  ],
  interpretation:
    "Cluster sits top-right; Mechanical is the divestiture candidate; Compliance is the integration risk to manage.",
};

describe("TwoByTwoMatrix", () => {
  it("renders all four quadrant cells with axis labels", () => {
    render(<TwoByTwoMatrix data={SAMPLE} />);
    expect(screen.getByTestId("two-by-two-cell-top_left")).toBeInTheDocument();
    expect(screen.getByTestId("two-by-two-cell-top_right")).toBeInTheDocument();
    expect(screen.getByTestId("two-by-two-cell-bottom_left")).toBeInTheDocument();
    expect(screen.getByTestId("two-by-two-cell-bottom_right")).toBeInTheDocument();
    expect(screen.getByTestId("x-axis-label").textContent).toBe("Strategic fit");
    expect(screen.getByTestId("y-axis-label").textContent).toBe("Ease of integration");
    expect(screen.getByTestId("x-axis-low").textContent).toBe("Low");
    expect(screen.getByTestId("x-axis-high").textContent).toBe("High");
    expect(screen.getByTestId("interpretation").textContent).toContain("Mechanical is the divestiture candidate");
  });

  it("places each item in its declared quadrant", () => {
    render(<TwoByTwoMatrix data={SAMPLE} />);
    const topRight = screen.getByTestId("two-by-two-cell-top_right");
    expect(within(topRight).getByText("Facilities Maintenance")).toBeInTheDocument();
    const bottomLeft = screen.getByTestId("two-by-two-cell-bottom_left");
    expect(within(bottomLeft).getByText("Mechanical Services")).toBeInTheDocument();
    const topLeft = screen.getByTestId("two-by-two-cell-top_left");
    expect(within(topLeft).getByText("Compliance")).toBeInTheDocument();
    // Verify no leakage between cells.
    expect(within(topRight).queryByText("Mechanical Services")).toBeNull();
  });

  it("opens the detail panel when an item is clicked and closes again", () => {
    render(<TwoByTwoMatrix data={SAMPLE} />);
    // Detail panel hidden initially.
    expect(screen.queryByTestId("two-by-two-detail")).toBeNull();
    // Click the Facilities Maintenance item.
    const buttons = screen.getAllByTestId("two-by-two-item");
    const fmBtn = buttons.find((b) => b.textContent?.includes("Facilities Maintenance"));
    expect(fmBtn).toBeTruthy();
    fireEvent.click(fmBtn!);
    const detail = screen.getByTestId("two-by-two-detail");
    expect(within(detail).getByText(/Strong strategic fit/i)).toBeInTheDocument();
    expect(within(detail).getByText("c-fm-1")).toBeInTheDocument();
    expect(within(detail).getByText("c-fm-2")).toBeInTheDocument();
    // Close.
    fireEvent.click(within(detail).getByText(/close/i));
    expect(screen.queryByTestId("two-by-two-detail")).toBeNull();
  });
});
