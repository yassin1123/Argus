import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/sectionDeepening", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/sectionDeepening")
  >("@/lib/api/sectionDeepening");
  return {
    ...actual,
    listDeepenings: vi.fn(),
  };
});

import DeepeningHistory from "../DeepeningHistory";
import * as api from "@/lib/api/sectionDeepening";

const listMock = api.listDeepenings as ReturnType<typeof vi.fn>;

const ROWS: api.Deepening[] = [
  {
    id: "d-newer",
    section_path: "synergy_estimate",
    depth_directive: "more cost detail",
    status: "complete",
    failure_reason: null,
    new_evidence_chunks_used: 20,
    cost_usd: 0.21,
    wall_seconds: 9.1,
    created_at: "2026-05-12T10:30:00Z",
    completed_at: "2026-05-12T10:30:09Z",
  },
  {
    id: "d-older",
    section_path: "risks",
    depth_directive: null,
    status: "failed",
    failure_reason: "evidence gap",
    new_evidence_chunks_used: 0,
    cost_usd: 0,
    wall_seconds: 4.5,
    created_at: "2026-05-12T09:00:00Z",
    completed_at: "2026-05-12T09:00:04Z",
  },
];

describe("DeepeningHistory", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("renders the count + expands to show items + click opens the deepening", async () => {
    listMock.mockResolvedValue(ROWS);
    const onOpen = vi.fn();

    render(<DeepeningHistory sessionId="sess-1" onOpenDeepening={onOpen} />);

    await waitFor(() => expect(listMock).toHaveBeenCalledWith("sess-1"));
    // Count appears
    await waitFor(() =>
      expect(screen.getByTestId("history-toggle").textContent).toContain("Previous deepenings (2)"),
    );
    // List is collapsed by default
    expect(screen.queryByTestId("history-list")).toBeNull();
    // Expand
    fireEvent.click(screen.getByTestId("history-toggle"));
    expect(screen.getByTestId("history-list")).toBeInTheDocument();
    expect(screen.getByTestId("history-item-d-newer")).toBeInTheDocument();
    expect(screen.getByTestId("history-item-d-older")).toBeInTheDocument();
    // Status badges
    expect(screen.getByTestId("history-status-d-newer").textContent).toBe("complete");
    expect(screen.getByTestId("history-status-d-older").textContent).toBe("failed");
    // Click newer item
    fireEvent.click(
      screen
        .getByTestId("history-item-d-newer")
        .querySelector("button") as HTMLButtonElement,
    );
    expect(onOpen).toHaveBeenCalledWith("d-newer", "synergy_estimate");
  });

  it("renders nothing when there are no items and no error", async () => {
    listMock.mockResolvedValue([]);
    const { container } = render(
      <DeepeningHistory sessionId="sess-1" onOpenDeepening={() => {}} />,
    );
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="deepening-history"]')).toBeNull();
  });

  it("reloads when reloadKey changes", async () => {
    listMock.mockResolvedValue(ROWS);
    const { rerender } = render(
      <DeepeningHistory sessionId="sess-1" onOpenDeepening={() => {}} reloadKey={0} />,
    );
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));
    rerender(
      <DeepeningHistory sessionId="sess-1" onOpenDeepening={() => {}} reloadKey={1} />,
    );
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
  });
});
