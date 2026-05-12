import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
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

describe("StatusPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    pollMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls and transitions queued → running → complete; shows View result on complete", async () => {
    pollMock
      .mockResolvedValueOnce(makeDetail({ status: "queued" }))
      .mockResolvedValueOnce(
        makeDetail({ status: "running", new_evidence_chunks_used: 12, wall_seconds: 4.2 }),
      )
      .mockResolvedValueOnce(
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
        pollIntervalMs={1000}
      />,
    );

    // Tick 1: queued initial poll
    await waitFor(() => {
      expect(pollMock).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("status-label").textContent).toMatch(/Queued/i);
    });

    // Tick 2: advance the interval, running with chunks landed
    await vi.advanceTimersByTimeAsync(1000);
    await waitFor(() => {
      expect(pollMock).toHaveBeenCalledTimes(2);
      expect(screen.getByTestId("status-label").textContent).toMatch(/Running/i);
      expect(screen.getByTestId("chunks-counter").textContent).toContain("12");
    });

    // Tick 3: complete; onTerminal fires + View result button appears
    await vi.advanceTimersByTimeAsync(1000);
    await waitFor(() => {
      expect(pollMock).toHaveBeenCalledTimes(3);
      expect(screen.getByTestId("status-label").textContent).toMatch(/Complete/i);
      expect(screen.getByTestId("view-result")).toBeInTheDocument();
      expect(onTerminal).toHaveBeenCalledTimes(1);
      const arg = onTerminal.mock.calls[0][0];
      expect(arg.status).toBe("complete");
    });
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
        pollIntervalMs={1000}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status-label").textContent).toMatch(/Failed/i);
      expect(screen.getByTestId("failure-reason").textContent).toContain("foo.bar");
      expect(screen.queryByTestId("view-result")).toBeNull();
      expect(onTerminal).toHaveBeenCalledTimes(1);
    });
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
        pollIntervalMs={5000}
      />,
    );
    await waitFor(() => expect(pollMock).toHaveBeenCalled());
    fireEvent.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalled();
  });
});
