import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ReviewHistory from "../ReviewHistory";
import type { ReviewHistoryEntry } from "@/lib/api/review";

const HISTORY: ReviewHistoryEntry[] = [
  {
    id: "rr-1",
    from_state: "draft",
    to_state: "in_review",
    action: "submit_for_review",
    actor_id: "abcdef1234567890",
    reviewer_id: "fedcba0987654321",
    feedback: null,
    created_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  },
  {
    id: "rr-2",
    from_state: "in_review",
    to_state: "changes_requested",
    action: "request_changes",
    actor_id: "fedcba0987654321",
    reviewer_id: null,
    feedback: {
      overall_note: "Tighten synergy estimate.",
      severity: "blocking",
      section_pointers: [
        {
          section_path: "synergy_estimate",
          note: "Sourcing weak.",
          severity: "blocking",
          resolved: false,
        },
        {
          section_path: "risks",
          note: "Add one more.",
          severity: "minor",
          resolved: true,
        },
      ],
    },
    created_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
  },
];

describe("ReviewHistory", () => {
  it("renders an empty state when no history is present", () => {
    render(<ReviewHistory history={[]} />);
    expect(screen.getByTestId("empty-history")).toHaveTextContent(/no review actions yet/i);
  });

  it("renders one row per entry with the action label + state arrow", () => {
    render(<ReviewHistory history={HISTORY} />);
    expect(screen.getByTestId("review-history-entry-rr-1")).toHaveTextContent("Submitted for review");
    expect(screen.getByTestId("review-history-entry-rr-1")).toHaveTextContent("draft → in_review");
    expect(screen.getByTestId("review-history-entry-rr-2")).toHaveTextContent("Requested changes");
    expect(screen.getByTestId("review-history-entry-rr-2")).toHaveTextContent("in_review → changes_requested");
  });

  it("only the request_changes entry has an expandable details panel", () => {
    render(<ReviewHistory history={HISTORY} />);
    // The submit_for_review entry has no expand button (feedback is null).
    expect(screen.queryByTestId("expand-rr-1")).toBeNull();
    // The request_changes entry has one.
    expect(screen.getByTestId("expand-rr-2")).toBeInTheDocument();
  });

  it("expanding the request_changes row reveals the structured feedback", () => {
    render(<ReviewHistory history={HISTORY} />);
    fireEvent.click(screen.getByTestId("expand-rr-2"));
    const details = screen.getByTestId("feedback-details-rr-2");
    expect(details).toHaveTextContent("Tighten synergy estimate.");
    expect(details).toHaveTextContent("Severity: blocking");
    expect(details).toHaveTextContent("synergy_estimate");
    expect(details).toHaveTextContent("[blocking]");
    expect(details).toHaveTextContent("open");
    expect(details).toHaveTextContent("risks");
    expect(details).toHaveTextContent("[minor]");
    expect(details).toHaveTextContent("resolved");
  });
});
