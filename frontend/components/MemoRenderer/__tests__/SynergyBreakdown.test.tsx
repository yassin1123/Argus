import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import SynergyBreakdown from "../M_and_A/SynergyBreakdown";

describe("SynergyBreakdown", () => {
  it("renders three piles with NPV row at the bottom", () => {
    render(
      <SynergyBreakdown
        data={{
          revenue_synergies: [
            {
              type: "Premium pricing headroom",
              magnitude_gbp_m: 1.8,
              timing_months: 12,
              confidence: "medium",
              basis_citations: ["WTP study"],
            },
          ],
          cost_synergies: [
            {
              type: "Procurement consolidation",
              magnitude_gbp_m: 12.0,
              timing_months: 18,
              confidence: "high",
              basis_citations: ["Pricing pack p.5"],
            },
          ],
          dis_synergies: [
            {
              type: "Customer attrition",
              magnitude_gbp_m: 2.4,
              timing_months: 9,
              confidence: "medium",
              basis_citations: ["WTP study big-ticket"],
            },
          ],
          net_present_value: {
            low_gbp_m: 38,
            base_gbp_m: 64,
            high_gbp_m: 92,
            discount_rate_pct: 11.5,
          },
          realization_timeline: "Year 1: 30%; Year 2: 75%; Year 3: 100%.",
        }}
      />,
    );

    const revenue = screen.getByTestId("synergy-pile-revenue");
    const cost = screen.getByTestId("synergy-pile-cost");
    const dis = screen.getByTestId("synergy-pile-dis");
    expect(revenue).toHaveTextContent("Premium pricing headroom");
    expect(revenue).toHaveTextContent("£1.8m");
    expect(cost).toHaveTextContent("Procurement consolidation");
    expect(cost).toHaveTextContent("£12m");
    expect(dis).toHaveTextContent("Customer attrition");
    expect(dis).toHaveTextContent("-£2.4m");
    // confidence chips render
    expect(within(cost).getByText(/high/i)).toBeInTheDocument();

    const npv = screen.getByTestId("synergy-npv");
    expect(npv).toHaveTextContent("£38m");
    expect(npv).toHaveTextContent("£64m");
    expect(npv).toHaveTextContent("£92m");
    expect(npv).toHaveTextContent("11.5%");

    expect(screen.getByText(/Year 1: 30%/)).toBeInTheDocument();
  });

  it("shows 'No items' when a pile is empty (and never crashes)", () => {
    render(
      <SynergyBreakdown
        data={{
          revenue_synergies: [],
          cost_synergies: [],
          dis_synergies: [],
        }}
      />,
    );
    const dis = screen.getByTestId("synergy-pile-dis");
    expect(dis).toHaveTextContent("No items.");
  });
});
