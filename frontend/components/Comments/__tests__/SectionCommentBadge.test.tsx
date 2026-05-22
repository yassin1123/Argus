import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import SectionCommentAffordance from "../SectionCommentAffordance";

describe("SectionCommentAffordance", () => {
  it("renders nothing when visible is false (non-member gate)", () => {
    const { container } = render(
      <SectionCommentAffordance
        sectionPath="synergy_estimate"
        unresolvedCount={3}
        totalCount={3}
        visible={false}
        onClick={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows the unresolved count when there are open threads", () => {
    render(
      <SectionCommentAffordance
        sectionPath="synergy_estimate"
        unresolvedCount={3}
        totalCount={5}
        visible
        onClick={() => {}}
      />,
    );
    const badge = screen.getByTestId("section-comment-badge-synergy_estimate");
    expect(badge.textContent).toBe("3");
    const button = screen.getByTestId(
      "section-comment-affordance-synergy_estimate",
    );
    expect(button.getAttribute("data-has-unresolved")).toBe("true");
  });

  it("falls back to the total count when all threads are resolved", () => {
    render(
      <SectionCommentAffordance
        sectionPath="risks"
        unresolvedCount={0}
        totalCount={2}
        visible
        onClick={() => {}}
      />,
    );
    // Still displays a count (the spec calls this 'persistent if the
    // section has comments').
    const badge = screen.getByTestId("section-comment-badge-risks");
    expect(badge.textContent).toBe("2");
    const button = screen.getByTestId("section-comment-affordance-risks");
    expect(button.getAttribute("data-has-unresolved")).toBe("false");
  });

  it("invokes onClick when clicked", () => {
    const onClick = vi.fn();
    render(
      <SectionCommentAffordance
        sectionPath="risks"
        unresolvedCount={1}
        totalCount={1}
        visible
        onClick={onClick}
      />,
    );
    fireEvent.click(screen.getByTestId("section-comment-affordance-risks"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
