import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/sectionDeepening", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/sectionDeepening")
  >("@/lib/api/sectionDeepening");
  return {
    ...actual,
    triggerDeepening: vi.fn(),
    listDeepenings: vi.fn(),
  };
});

import TriggerModal from "../TriggerModal";
import * as api from "@/lib/api/sectionDeepening";

const triggerDeepeningMock = api.triggerDeepening as ReturnType<typeof vi.fn>;
const listDeepeningsMock = api.listDeepenings as ReturnType<typeof vi.fn>;

describe("TriggerModal", () => {
  beforeEach(() => {
    triggerDeepeningMock.mockReset();
    listDeepeningsMock.mockReset();
  });

  it("renders header + directive textarea + estimate + buttons", () => {
    render(
      <TriggerModal
        sessionId="sess-1"
        sectionPath="synergy_estimate"
        onTriggered={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText(/Deepen section: Synergy estimate/i)).toBeInTheDocument();
    expect(screen.getByTestId("depth-directive")).toBeInTheDocument();
    expect(screen.getByTestId("trigger-submit")).toHaveTextContent("Run deepening");
    expect(screen.getByText(/Estimated cost/i)).toBeInTheDocument();
    expect(screen.getByText(/Estimated time/i)).toBeInTheDocument();
  });

  it("fires triggerDeepening on submit and invokes onTriggered with the new id", async () => {
    triggerDeepeningMock.mockResolvedValue({
      status: "queued",
      session_id: "sess-1",
      section_path: "synergy_estimate",
      depth_directive: "more depth please",
    });
    listDeepeningsMock.mockResolvedValue([
      {
        id: "deepening-xyz",
        section_path: "synergy_estimate",
        depth_directive: "more depth please",
        status: "queued",
        failure_reason: null,
        new_evidence_chunks_used: 0,
        cost_usd: 0,
        wall_seconds: 0,
        created_at: new Date().toISOString(),
        completed_at: null,
      },
    ]);
    const onTriggered = vi.fn();

    render(
      <TriggerModal
        sessionId="sess-1"
        sectionPath="synergy_estimate"
        onTriggered={onTriggered}
        onCancel={() => {}}
      />,
    );

    const textarea = screen.getByTestId("depth-directive") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "more depth please" } });
    fireEvent.click(screen.getByTestId("trigger-submit"));

    await waitFor(() => {
      expect(triggerDeepeningMock).toHaveBeenCalledWith(
        "sess-1",
        "synergy_estimate",
        "more depth please",
      );
      expect(listDeepeningsMock).toHaveBeenCalledWith("sess-1");
      expect(onTriggered).toHaveBeenCalledWith(
        "deepening-xyz",
        "synergy_estimate",
        "more depth please",
      );
    });
  });

  it("surfaces an error message when the trigger call fails", async () => {
    triggerDeepeningMock.mockRejectedValue(new Error("403: read-only role"));
    render(
      <TriggerModal
        sessionId="sess-1"
        sectionPath="risks"
        onTriggered={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("trigger-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("trigger-error").textContent).toContain("403: read-only role");
    });
  });

  it("validates non-empty section_path before submitting", async () => {
    render(
      <TriggerModal
        sessionId="sess-1"
        sectionPath=" " // whitespace-only
        onTriggered={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("trigger-submit"));
    await waitFor(() => {
      expect(triggerDeepeningMock).not.toHaveBeenCalled();
    });
  });
});
