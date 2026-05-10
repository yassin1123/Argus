import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import ValuationRangeTable from "../M_and_A/ValuationRangeTable";

describe("ValuationRangeTable", () => {
  it("renders three columns with £ values and methodologies", () => {
    render(
      <ValuationRangeTable
        data={{
          low: {
            gbp_m: 175,
            methodology: "DCF @ WACC 12% conservative",
            key_assumptions: ["Home LFL -2%", "Supplier renegotiation £6m"],
          },
          base: {
            gbp_m: 210,
            methodology: "DCF @ WACC 11.5% triangulated against EV/EBITDA 9.7x",
            key_assumptions: ["Home LFL -1%", "Supplier renegotiation £12m"],
          },
          high: {
            gbp_m: 245,
            methodology: "EV/EBITDA 11.3x precedents",
            key_assumptions: ["Home LFL flat", "Online expansion to 18%"],
          },
          multiples_implied: { "EV/EBITDA": 9.7, "EV/Sales": 1.04 },
          comparable_transactions_cited: [
            {
              target: "WHSmith Travel",
              acquirer: "Lagardère",
              year: 2023,
              multiple: "11.0x EV/EBITDA",
              source_citation: "Mergermarket",
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("valuation-range-table")).toBeInTheDocument();
    expect(screen.getByTestId("valuation-low-cell")).toHaveTextContent("£175m");
    expect(screen.getByTestId("valuation-base-cell")).toHaveTextContent("£210m");
    expect(screen.getByTestId("valuation-high-cell")).toHaveTextContent("£245m");
    expect(screen.getByTestId("valuation-low-method")).toHaveTextContent(
      "DCF @ WACC 12% conservative",
    );
    expect(screen.getByTestId("multiples-implied")).toHaveTextContent("EV/EBITDA: 9.70x");
    expect(screen.getByTestId("multiples-implied")).toHaveTextContent("EV/Sales: 1.04x");
    expect(screen.getByTestId("comparable-transactions")).toHaveTextContent("WHSmith Travel");
  });

  it("renders em-dashes for missing values without crashing", () => {
    render(<ValuationRangeTable data={{}} />);
    const low = screen.getByTestId("valuation-low-cell");
    expect(within(low).getAllByText("—").length).toBeGreaterThan(0);
  });
});
