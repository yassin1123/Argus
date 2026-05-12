import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/sectionDeepening", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/sectionDeepening")
  >("@/lib/api/sectionDeepening");
  return {
    ...actual,
    pollDeepening: vi.fn(),
  };
});

import StatusPanel from "../StatusPanel";
import * as api from "@/lib/api/sectionDeepening";

const pollMock = api.pollDeepening as ReturnType<typeof vi.fn>;

function makeDetail(overrides: Partial<api.DeepeningDetail> = {}): api.DeepeningDetail {
  return {
    id: "d-1",
    session_id: "sess-1",
    firm_id: "f-1",
    triggered_by: "u-1",
    section_path: "synergy_estimate",
    depth_directive: null,
    status: "queued",
    failure_reason: null,
    original_section_json: {},
    deepened_section_json: null,
    new_claim_ids: [],
    new_evidence_chunks_used: 0,
    cost_usd: 0,
    wall_seconds: 0,
    created_at: new Date().toISOString(),
    completed_at: null,
    ...overrides,
  };
}

// Real timers + short interval so waitFor + the async polling
// lifecycle compose cleanly. Fake timers + async micro-tasks +
// React effect cleanup race in subtle ways that aren't worth
// fighting at the test layer — the polling interval contract is
// configurable so we can just drive it fast.
const FAST_POLL = 30;

describe("StatusPanel", () => {
  beforeEach(() => {
    pollMock.mockReset();
  });

  it("polls and transitions queued → running → complete; shows View result on complete", async () => {
    pollMock
      .mockResolvedValueOnce(makeDetail({ status: "queued" }))
      .mockResolvedValueOnce(
        makeDetail({ status: "running", new_evidence_chunks_used: 12, wall_seconds: 4.2 }),
      )
      .mockResolvedValue(
        makeDetail({
          status: "complete",
          new_evidence_chunks_used: 18,
          wall_seconds: 14.6,
          cost_usd: 0.21,
          deepened_section_json: { revenue_synergies: [] },
        }),
      );
    const onTerminal = vi.fn();
    const onClose = vi.fn();

    render(
      <StatusPanel
        sessionId="sess-1"
        deepeningId="d-1"
        sectionPath="synergy_estimate"
        onTerminal={onTerminal}
        onClose={onClose}
        pollIntervalMs={FAST_POLL}
      />,
    );

    // Eventually transitions to complete via real-timer polling.
    await waitFor(
      () => {
        expect(screen.getByTestId("status-label").textContent).toMatch(/Complete/i);
        expect(screen.getByTestId("view-result")).toBeInTheDocument();
        expect(onTerminal).toHaveBeenCalled();
      },
      { timeout: 2000 },
    );
    // Terminal-state semantics: the panel fired onTerminal at least once
    // with status=complete on the first complete response it saw.
    const completeArg = onTerminal.mock.calls.find(
      (c) => c[0]?.status === "complete",
    );
    expect(completeArg).toBeTruthy();
    expect(pollMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("surfaces failure_reason and does NOT show View result on failed", async () => {
    pollMock.mockResolvedValue(
      makeDetail({
        status: "failed",
        failure_reason: "section_path 'foo.bar': key 'foo' not found at (root)",
      }),
    );
    const onTerminal = vi.fn();

    render(
      <StatusPanel
        sessionId="sess-1"
        deepeningId="d-1"
        sectionPath="foo.bar"
        onTerminal={onTerminal}
        onClose={() => {}}
        pollIntervalMs={FAST_POLL}
      />,
    );

    await waitFor(
      () => {
        expect(screen.getByTestId("status-label").textContent).toMatch(/Failed/i);
        expect(screen.getByTestId("failure-reason").textContent).toContain("foo.bar");
        expect(onTerminal).toHaveBeenCalled();
      },
      { timeout: 2000 },
    );
    expect(screen.queryByTestId("view-result")).toBeNull();
  });

  it("clicking Close calls onClose", async () => {
    pollMock.mockResolvedValue(makeDetail({ status: "running" }));
    const onClose = vi.fn();

    render(
      <StatusPanel
        sessionId="sess-1"
        deepeningId="d-1"
        sectionPath="key_reasons"
        onClose={onClose}
        pollIntervalMs={500}
      />,
    );
    await waitFor(() => expect(pollMock).toHaveBeenCalled(), { timeout: 2000 });
    fireEvent.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalled();
  });
});
