import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import SchemaDrivenSection from "../SchemaDrivenSection";

describe("SchemaDrivenSection", () => {
  it("renders a string as a paragraph", () => {
    render(<SchemaDrivenSection title="recommendation" value="Acquire at £210m" />);
    expect(screen.getByText("Recommendation")).toBeInTheDocument();
    expect(screen.getByText("Acquire at £210m")).toBeInTheDocument();
  });

  it("renders a list of strings as a bullet list", () => {
    render(
      <SchemaDrivenSection
        title="key_reasons"
        value={["First reason", "Second reason", "Third reason"]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("First reason");
  });

  it("renders a list of dicts as a table with humanized headers", () => {
    render(
      <SchemaDrivenSection
        title="decision_criteria"
        value={[
          { criterion: "Time to revenue", weight: "high" },
          { criterion: "Capex intensity", weight: "medium" },
        ]}
      />,
    );
    const table = screen.getByTestId("schema-driven-table");
    expect(table).toBeInTheDocument();
    expect(table).toHaveTextContent("Criterion");
    expect(table).toHaveTextContent("Weight");
    expect(table).toHaveTextContent("Time to revenue");
    expect(table).toHaveTextContent("Capex intensity");
  });

  it("recurses into nested dicts as labeled subsections", () => {
    render(
      <SchemaDrivenSection
        title="financial_profile"
        value={{
          margin_profile: {
            gross_margin: "36.4%",
            ebitda_margin: "10.7%",
          },
        }}
      />,
    );
    expect(screen.getByText("Financial Profile")).toBeInTheDocument();
    expect(screen.getByText("Margin Profile")).toBeInTheDocument();
    expect(screen.getByText("Gross Margin")).toBeInTheDocument();
    expect(screen.getByText("36.4%")).toBeInTheDocument();
  });

  it("never raw-JSON-dumps unknown shapes (per W7/D3 hard rule)", () => {
    // An empty array still renders a placeholder ("—"), not raw `[]`.
    const { container } = render(<SchemaDrivenSection title="risks" value={[]} />);
    expect(container.textContent).not.toContain("[]");
    expect(container.textContent).not.toContain("{}");
  });

  it("renders empty objects/strings as a non-empty placeholder", () => {
    const { container } = render(<SchemaDrivenSection title="caveats" value="" />);
    // The "—" placeholder appears for empty values rather than nothing
    // — the operator can see the field exists but is blank.
    expect(container.textContent).toContain("—");
  });
});
