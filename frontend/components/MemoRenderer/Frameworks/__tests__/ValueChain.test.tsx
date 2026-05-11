import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import ValueChain, { type ValueChainData } from "../ValueChain";

const SAMPLE: ValueChainData = {
  business_context: "UK contract services arm — facilities maintenance + mechanical services lines.",
  activities: [
    {
      name: "Inbound logistics",
      category: "primary",
      canonical_step: "inbound_logistics",
      assessment: "Supplier network is mature with redundant routing across UK depots.",
      competitive_implication: "Cost parity with comparable peers; no edge here.",
      evidence_citations: ["c-il-1"],
    },
    {
      name: "Operations",
      category: "primary",
      canonical_step: "operations",
      assessment: "Plant utilisation runs 84% vs 71% industry median; lean program bedded in.",
      competitive_implication: "Cost-per-unit advantage of ~3% vs nearest comparable.",
      evidence_citations: ["c-op-1", "c-op-2"],
    },
    {
      name: "HR",
      category: "support",
      canonical_step: "hr_management",
      assessment: "High retention on apprentice cohorts; weak senior bench depth.",
      competitive_implication: "Succession risk on three operational leaders within 24 months.",
      evidence_citations: ["c-hr-1"],
    },
    {
      name: "Procurement",
      category: "support",
      canonical_step: "procurement",
      assessment: "Single-source on critical inputs (35% of opex).",
      competitive_implication: "Supplier consolidation post-close could net 4-6% margin.",
      evidence_citations: ["c-pr-1"],
    },
  ],
  overall_thesis: "Wins on operations + procurement; HR is the bench-depth bet for the buyer.",
};

describe("ValueChain", () => {
  it("renders both rows with the business context and overall thesis", () => {
    render(<ValueChain data={SAMPLE} />);
    expect(screen.getByTestId("value-chain")).toBeInTheDocument();
    expect(screen.getByTestId("value-chain-row-primary")).toBeInTheDocument();
    expect(screen.getByTestId("value-chain-row-support")).toBeInTheDocument();
    expect(screen.getByTestId("business-context").textContent).toContain("UK contract services arm");
    expect(screen.getByTestId("overall-thesis").textContent).toContain("HR is the bench-depth bet");
  });

  it("places primary activities in the primary row and support activities in the support row", () => {
    render(<ValueChain data={SAMPLE} />);
    const primaryRow = screen.getByTestId("value-chain-row-primary");
    const supportRow = screen.getByTestId("value-chain-row-support");

    // Primary row contains operations + inbound_logistics.
    expect(within(primaryRow).getByTestId("value-chain-activity-operations")).toBeInTheDocument();
    expect(within(primaryRow).getByTestId("value-chain-activity-inbound_logistics")).toBeInTheDocument();
    // Support row contains hr_management + procurement.
    expect(within(supportRow).getByTestId("value-chain-activity-hr_management")).toBeInTheDocument();
    expect(within(supportRow).getByTestId("value-chain-activity-procurement")).toBeInTheDocument();
    // No leakage.
    expect(within(primaryRow).queryByTestId("value-chain-activity-hr_management")).toBeNull();
    expect(within(supportRow).queryByTestId("value-chain-activity-operations")).toBeNull();
  });

  it("renders assessment, competitive implication, and citations for each activity", () => {
    render(<ValueChain data={SAMPLE} />);
    const ops = screen.getByTestId("value-chain-activity-operations");
    expect(within(ops).getByTestId("activity-assessment").textContent).toContain("Plant utilisation runs 84%");
    expect(within(ops).getByTestId("activity-implication").textContent).toContain("Cost-per-unit advantage");
    expect(within(ops).getByText("c-op-1")).toBeInTheDocument();
    expect(within(ops).getByText("c-op-2")).toBeInTheDocument();
  });
});
