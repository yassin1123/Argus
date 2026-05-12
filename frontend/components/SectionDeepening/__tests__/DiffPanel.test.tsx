import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/sectionDeepening", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/sectionDeepening")
  >("@/lib/api/sectionDeepening");
  return {
    ...actual,
    acceptDeepening: vi.fn(),
    rejectDeepening: vi.fn(),
  };
});

import DiffPanel from "../DiffPanel";
import * as api from "@/lib/api/sectionDeepening";

const acceptMock = api.acceptDeepening as ReturnType<typeof vi.fn>;
const rejectMock = api.rejectDeepening as ReturnType<typeof vi.fn>;

function makeDetail(
  overrides: Partial<api.DeepeningDetail> = {},
): api.DeepeningDetail {
  return {
    id: "d-1",
    session_id: "sess-1",
    firm_id: "f-1",
    triggered_by: "u-1",
    section_path: "key_reasons",
    depth_directive: null,
    status: "complete",
    failure_reason: null,
    original_section_json: [
      "Bavaria procurement cycles run faster than NRW.",
      "Three reference customers in-region.",
    ],
    deepened_section_json: [
      "Bavaria procurement cycles run 6-8 weeks faster than NRW (verified).",
      "Three reference customers anchor logo-zero meaningfully.",
      "Mittelstand budgets shift in Q4 2025 (Bundesverband data).",
    ],
    new_claim_ids: ["c-mit-q4", "c-bvb-2025"],
    new_evidence_chunks_used: 12,
    cost_usd: 0.23,
    wall_seconds: 47,
    created_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("DiffPanel", () => {
  beforeEach(() => {
    acceptMock.mockReset();
    rejectMock.mockReset();
  });

  it("renders header, cost row, two columns, new-citations callout", () => {
    render(
      <DiffPanel
        sessionId="sess-1"
        detail={makeDetail()}
        onAccepted={() => {}}
        onRejected={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/Deepened section: Key reasons/i)).toBeInTheDocument();
    // Cost row contents
    const cost = screen.getByTestId("cost-row");
    expect(cost.textContent).toContain("$0.23");
    expect(cost.textContent).toContain("47 seconds");
    expect(cost.textContent).toContain("12 new evidence chunks");
    expect(cost.textContent).toContain("2 new claims");
    // Two columns
    expect(screen.getByTestId("diff-column-left")).toBeInTheDocument();
    expect(screen.getByTestId("diff-column-right")).toBeInTheDocument();
    // New citations callout shows the claim_ids
    const citations = screen.getByTestId("new-citations");
    expect(citations.textContent).toContain("c-mit-q4");
    expect(citations.textContent).toContain("c-bvb-2025");
  });

  it("highlights added words on the right column", () => {
    render(
      <DiffPanel
        sessionId="sess-1"
        detail={makeDetail()}
        onAccepted={() => {}}
        onRejected={() => {}}
        onClose={() => {}}
      />,
    );
    const right = screen.getByTestId("diff-column-right");
    // At least one "added" segment renders on the right (the new
    // Mittelstand sentence has words that don't appear in the
    // original).
    const added = right.querySelectorAll('[data-testid="diff-added"]');
    expect(added.length).toBeGreaterThan(0);
  });

  it("accept button fires acceptDeepening + onAccepted with new_payload", async () => {
    acceptMock.mockResolvedValue({
      deepening_id: "d-1",
      status: "accepted",
      section_path: "key_reasons",
      new_payload: { recommendation: "x", key_reasons: ["a", "b", "c", "d"] },
    });
    const onAccepted = vi.fn();
    render(
      <DiffPanel
        sessionId="sess-1"
        detail={makeDetail()}
        onAccepted={onAccepted}
        onRejected={() => {}}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("accept-button"));
    await waitFor(() => {
      expect(acceptMock).toHaveBeenCalledWith("sess-1", "d-1");
      expect(onAccepted).toHaveBeenCalledWith({
        recommendation: "x",
        key_reasons: ["a", "b", "c", "d"],
      });
    });
  });

  it("reject button fires rejectDeepening + onRejected", async () => {
    rejectMock.mockResolvedValue({
      deepening_id: "d-1",
      status: "rejected",
    });
    const onRejected = vi.fn();
    render(
      <DiffPanel
        sessionId="sess-1"
        detail={makeDetail()}
        onAccepted={() => {}}
        onRejected={onRejected}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("reject-button"));
    await waitFor(() => {
      expect(rejectMock).toHaveBeenCalledWith("sess-1", "d-1");
      expect(onRejected).toHaveBeenCalled();
    });
  });

  it("surfaces accept errors and re-enables buttons", async () => {
    acceptMock.mockRejectedValue(new Error("409: section drifted"));
    render(
      <DiffPanel
        sessionId="sess-1"
        detail={makeDetail()}
        onAccepted={() => {}}
        onRejected={() => {}}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("accept-button"));
    await waitFor(() => {
      expect(screen.getByTestId("diff-error").textContent).toContain("409: section drifted");
      // Button label resets so the consultant can retry.
      expect(screen.getByTestId("accept-button").textContent).toContain("Accept and merge");
    });
  });

  it("Save for later fires onClose without calling accept/reject", () => {
    const onClose = vi.fn();
    render(
      <DiffPanel
        sessionId="sess-1"
        detail={makeDetail()}
        onAccepted={() => {}}
        onRejected={() => {}}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByText("Save for later"));
    expect(onClose).toHaveBeenCalled();
    expect(acceptMock).not.toHaveBeenCalled();
    expect(rejectMock).not.toHaveBeenCalled();
  });
});
