import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { MyWork } from "@/lib/api/collaboration";

vi.mock("@/lib/api/collaboration", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/collaboration")>(
    "@/lib/api/collaboration",
  );
  return {
    ...actual,
    getMyWork: vi.fn(),
    getSessionWork: vi.fn(),
    completeTask: vi.fn(),
    createTask: vi.fn(),
  };
});

import MyWorkDashboard from "../MyWorkDashboard";
import {
  completeTask,
  createTask,
  getMyWork,
  getSessionWork,
} from "@/lib/api/collaboration";

const getMyWorkMock = getMyWork as unknown as ReturnType<typeof vi.fn>;
const getSessionWorkMock = getSessionWork as unknown as ReturnType<typeof vi.fn>;
const completeTaskMock = completeTask as unknown as ReturnType<typeof vi.fn>;
const createTaskMock = createTask as unknown as ReturnType<typeof vi.fn>;

function makeWork(): MyWork {
  const t1 = {
    source: "derived" as const,
    task_type: "change_request",
    session_id: "s-A",
    section_path: "synergy_estimate",
    source_ref: "rr-1",
    summary: "Address change request on synergy_estimate (blocking)",
    priority: "high" as const,
    created_at: "2026-05-22T12:00:00Z",
    extra: {},
  };
  const t2 = {
    source: "derived" as const,
    task_type: "mention",
    session_id: "s-A",
    section_path: null,
    source_ref: "c-1",
    summary: "You were @-mentioned",
    priority: "medium" as const,
    created_at: "2026-05-22T11:00:00Z",
    extra: {},
  };
  const t3 = {
    source: "explicit" as const,
    task_type: "explicit",
    session_id: "s-B",
    section_path: null,
    source_ref: "t-1",
    summary: "Ping client lawyer about SPA timeline",
    priority: "medium" as const,
    created_at: "2026-05-22T10:00:00Z",
    extra: {},
  };
  return {
    user_id: "u-alex",
    scope: "all",
    tasks: [t1, t2, t3],
    by_engagement: {
      "s-A": {
        session_id: "s-A",
        engagement_title: "Kestrel",
        tasks: [t1, t2],
        counts: { high: 1, medium: 1, low: 0, total: 2 },
      },
      "s-B": {
        session_id: "s-B",
        engagement_title: "BlueWave",
        tasks: [t3],
        counts: { high: 0, medium: 1, low: 0, total: 1 },
      },
    },
    totals: { high: 1, medium: 2, low: 0 },
  };
}

describe("MyWorkDashboard", () => {
  beforeEach(() => {
    getMyWorkMock.mockReset();
    getSessionWorkMock.mockReset();
    completeTaskMock.mockReset();
    createTaskMock.mockReset();
  });

  it("renders grouped engagement buckets with priority counts", async () => {
    getMyWorkMock.mockResolvedValue(makeWork());
    render(<MyWorkDashboard currentUserId="u-alex" />);
    await waitFor(() =>
      expect(screen.getByTestId("my-work-engagement-s-A")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("my-work-engagement-s-B")).toBeInTheDocument();
    expect(screen.getByTestId("my-work-totals").textContent).toContain("1 high");
  });

  it("completes an explicit task via checkbox", async () => {
    getMyWorkMock.mockResolvedValue(makeWork());
    completeTaskMock.mockResolvedValue({});
    render(<MyWorkDashboard currentUserId="u-alex" />);
    await waitFor(() =>
      expect(screen.getByTestId("my-work-task-t-1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("my-work-complete-t-1"));
    await waitFor(() => expect(completeTaskMock).toHaveBeenCalledWith("t-1"));
  });

  it("derived task fires onOpenTask when clicked", async () => {
    getMyWorkMock.mockResolvedValue(makeWork());
    const onOpenTask = vi.fn();
    render(<MyWorkDashboard currentUserId="u-alex" onOpenTask={onOpenTask} />);
    await waitFor(() =>
      expect(screen.getByTestId("my-work-task-rr-1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("my-work-open-rr-1"));
    expect(onOpenTask).toHaveBeenCalledTimes(1);
    expect(onOpenTask.mock.calls[0][0].source_ref).toBe("rr-1");
  });

  it("uses /sessions/{id}/work when sessionId is passed", async () => {
    getSessionWorkMock.mockResolvedValue(makeWork());
    render(<MyWorkDashboard sessionId="s-A" currentUserId="u-alex" compact />);
    await waitFor(() =>
      expect(getSessionWorkMock).toHaveBeenCalledWith("s-A"),
    );
  });
});
