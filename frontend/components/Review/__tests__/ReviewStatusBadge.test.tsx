import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import ReviewStatusBadge from "../ReviewStatusBadge";

describe("ReviewStatusBadge", () => {
  it("renders the draft variant by default when state is missing", () => {
    render(<ReviewStatusBadge state={null} />);
    const badge = screen.getByTestId("review-status-badge-draft");
    expect(badge).toBeInTheDocument();
    expect(badge.dataset.state).toBe("draft");
    expect(badge.className).toContain("text-argus-tertiary");
  });

  it("renders the right colour + label for every state", () => {
    const cases: Array<[
      "draft" | "in_review" | "changes_requested" | "approved" | "delivered",
      string,
      string,
    ]> = [
      ["draft", "Draft", "text-argus-tertiary"],
      ["in_review", "In review", "text-blue-700"],
      ["changes_requested", "Changes requested", "text-amber-700"],
      ["approved", "Approved", "text-emerald-700"],
      ["delivered", "Delivered", "text-purple-700"],
    ];
    for (const [state, label, expectedColor] of cases) {
      const { unmount } = render(<ReviewStatusBadge state={state} />);
      const badge = screen.getByTestId(`review-status-badge-${state}`);
      expect(badge).toHaveTextContent(label);
      expect(badge.className).toContain(expectedColor);
      expect(badge.getAttribute("title")).toContain(label);
      unmount();
    }
  });

  it("respects the size prop", () => {
    const { rerender } = render(<ReviewStatusBadge state="approved" size="sm" />);
    expect(screen.getByTestId("review-status-badge-approved").className).toContain(
      "text-[10px]",
    );
    rerender(<ReviewStatusBadge state="approved" size="md" />);
    expect(screen.getByTestId("review-status-badge-approved").className).toContain(
      "text-[11px]",
    );
  });
});
