import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import PortersFiveForces, { type PortersFiveForcesData } from "../PortersFiveForces";

const baseForce = (intensity: "low" | "moderate" | "high") => ({
  intensity,
  rationale:
    "Three large players hold 62% share; switching costs are non-trivial but not lock-in.",
  key_drivers: ["High fixed costs", "Slow demand growth", "Moderate differentiation"],
  evidence_citations: ["c1", "c2"],
});

const SAMPLE: PortersFiveForcesData = {
  market_definition: "UK industrial facilities maintenance — listed + private firms above £50m revenue.",
  rivalry: baseForce("high"),
  supplier_power: baseForce("low"),
  buyer_power: baseForce("high"),
  substitute_threat: baseForce("low"),
  new_entrant_threat: baseForce("moderate"),
  overall_attractiveness: "moderate",
  overall_rationale: "Buyer power offsets supplier weakness; rivalry capped by structural costs.",
};

describe("PortersFiveForces", () => {
  it("renders all five force cards in canonical order", () => {
    render(<PortersFiveForces data={SAMPLE} />);
    expect(screen.getByTestId("porters-force-rivalry")).toBeInTheDocument();
    expect(screen.getByTestId("porters-force-supplier_power")).toBeInTheDocument();
    expect(screen.getByTestId("porters-force-buyer_power")).toBeInTheDocument();
    expect(screen.getByTestId("porters-force-substitute_threat")).toBeInTheDocument();
    expect(screen.getByTestId("porters-force-new_entrant_threat")).toBeInTheDocument();
    expect(screen.getByTestId("market-definition").textContent).toContain("UK industrial facilities maintenance");
    expect(screen.getByTestId("overall-rationale").textContent).toContain("Buyer power offsets supplier weakness");
  });

  it("renders intensity badges with the correct semantic tone for each force", () => {
    render(<PortersFiveForces data={SAMPLE} />);
    const rivalryCard = screen.getByTestId("porters-force-rivalry");
    const rivalryBadge = within(rivalryCard).getByTestId("intensity-badge");
    expect(rivalryBadge.getAttribute("data-intensity")).toBe("high");
    // High intensity = contested (red-tone) class present
    expect(rivalryBadge.className).toContain("argus-contested");

    const supplierCard = screen.getByTestId("porters-force-supplier_power");
    const supplierBadge = within(supplierCard).getByTestId("intensity-badge");
    expect(supplierBadge.getAttribute("data-intensity")).toBe("low");
    expect(supplierBadge.className).toContain("argus-firm"); // low = firm (green)

    const newEntrantCard = screen.getByTestId("porters-force-new_entrant_threat");
    const newEntrantBadge = within(newEntrantCard).getByTestId("intensity-badge");
    expect(newEntrantBadge.getAttribute("data-intensity")).toBe("moderate");
    expect(newEntrantBadge.className).toContain("argus-accent"); // moderate = accent (amber)
  });

  it("renders key drivers as chips and evidence citations", () => {
    render(<PortersFiveForces data={SAMPLE} />);
    const rivalryCard = screen.getByTestId("porters-force-rivalry");
    const drivers = within(rivalryCard).getByTestId("key-drivers");
    expect(within(drivers).getByText("High fixed costs")).toBeInTheDocument();
    expect(within(drivers).getByText("Slow demand growth")).toBeInTheDocument();
    expect(within(drivers).getByText("Moderate differentiation")).toBeInTheDocument();
    const citations = within(rivalryCard).getAllByTestId("evidence-citation");
    expect(citations.map((c) => c.textContent)).toEqual(["c1", "c2"]);
  });
});
