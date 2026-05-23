import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { OverviewResponse } from "@/lib/api/comments";

vi.mock("@/lib/api/comments", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/comments")>(
    "@/lib/api/comments",
  );
  return {
    ...actual,
    getOverview: vi.fn(),
    resolveSection: vi.fn(),
    getCounts: vi.fn(),
    listThreads: vi.fn(),
  };
});

import CommentsController from "../CommentsController";
import CommentOverview from "../CommentOverview";
import {
  getCounts,
  getOverview,
  listThreads,
  resolveSection,
} from "@/lib/api/comments";

const getOverviewMock = getOverview as unknown as ReturnType<typeof vi.fn>;
const resolveSectionMock = resolveSection as unknown as ReturnType<typeof vi.fn>;
const getCountsMock = getCounts as unknown as ReturnType<typeof vi.fn>;
const listThreadsMock = listThreads as unknown as ReturnType<typeof vi.fn>;

function makeOverview(): OverviewResponse {
  const now = new Date().toISOString();
  return {
    groups: [
      {
        key: "section:synergy_estimate",
        label: "Section: synergy_estimate",
        anchor_type: "section",
        anchor_ref: { section_path: "synergy_estimate" },
        threads: [
          {
            root: {
              id: "c1",
              session_id: "s1",
              firm_id: "f1",
              parent_comment_id: null,
              anchor_type: "section",
              anchor_ref: { section_path: "synergy_estimate" },
              body: "Tighten the synergy basis.",
              mentioned_user_ids: [],
              author_id: "u-alex",
              resolved: false,
              resolved_by: null,
              resolved_at: null,
              created_at: now,
              updated_at: now,
              edited_at: null,
              deleted_at: null,
            },
            replies: [],
            resolved: false,
            orphaned: false,
          },
        ],
        unresolved: 1,
        total: 1,
      },
      {
        key: "artifact:art-1",
        label: "Artifact: art-1",
        anchor_type: "artifact",
        anchor_ref: { artifact_id: "art-1" },
        threads: [
          {
            root: {
              id: "c2",
              session_id: "s1",
              firm_id: "f1",
              parent_comment_id: null,
              anchor_type: "artifact",
              anchor_ref: { artifact_id: "art-1" },
              body: "Reword the recommendation line.",
              mentioned_user_ids: [],
              author_id: "u-sarah",
              resolved: false,
              resolved_by: null,
              resolved_at: null,
              created_at: now,
              updated_at: now,
              edited_at: null,
              deleted_at: null,
            },
            replies: [],
            resolved: false,
            orphaned: false,
          },
        ],
        unresolved: 1,
        total: 1,
      },
    ],
    unresolved_total: 2,
    total: 2,
  };
}

const MEMBERS = [
  { user_id: "u-alex", email: "alex.chen@m.invalid", full_name: "Alex Chen" },
  { user_id: "u-sarah", email: "sarah.kim@m.invalid", full_name: "Sarah Kim" },
];

function renderOverview(canResolve = true) {
  return render(
    <CommentsController
      sessionId="s1"
      currentUserId="u-alex"
      firmMembers={MEMBERS}
      canComment
    >
      <CommentOverview
        sessionId="s1"
        currentUserId="u-alex"
        firmMembers={MEMBERS}
        canResolveSections={canResolve}
      />
    </CommentsController>,
  );
}

describe("CommentOverview", () => {
  beforeEach(() => {
    getOverviewMock.mockReset();
    resolveSectionMock.mockReset();
    getCountsMock.mockResolvedValue({
      by_anchor_type: {},
      by_section_path: {},
      unresolved_total: 0,
      total: 0,
    });
    listThreadsMock.mockResolvedValue({
      session_id: "s1",
      threads: [],
      total: 0,
    });
  });

  it("renders groups with labels + counts from the API", async () => {
    getOverviewMock.mockResolvedValue(makeOverview());
    renderOverview();
    await waitFor(() =>
      expect(
        screen.getByTestId("overview-group-section:synergy_estimate"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("overview-group-label-section:synergy_estimate")
        .textContent,
    ).toBe("Section: synergy_estimate");
    expect(screen.getByTestId("overview-group-artifact:art-1")).toBeInTheDocument();
    expect(screen.getByTestId("overview-unresolved-count").textContent)
      .toContain("2 unresolved");
  });

  it("re-fetches with resolved=false when the status filter changes", async () => {
    getOverviewMock.mockResolvedValue(makeOverview());
    renderOverview();
    await waitFor(() => expect(getOverviewMock).toHaveBeenCalled());
    getOverviewMock.mockClear();

    fireEvent.change(screen.getByTestId("overview-resolved-filter"), {
      target: { value: "resolved" },
    });
    await waitFor(() => expect(getOverviewMock).toHaveBeenCalled());
    const lastCall = getOverviewMock.mock.calls.at(-1);
    expect(lastCall?.[1]).toEqual(
      expect.objectContaining({ resolved: true }),
    );
  });

  it("calls resolveSection when Resolve all is clicked", async () => {
    getOverviewMock.mockResolvedValue(makeOverview());
    resolveSectionMock.mockResolvedValue({
      section_path: "synergy_estimate",
      resolved_count: 1,
      resolved_comment_ids: ["c1"],
    });
    // Bypass the native confirm() dialog in jsdom.
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderOverview(true);
    await waitFor(() =>
      expect(
        screen.getByTestId("overview-bulk-resolve-synergy_estimate"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByTestId("overview-bulk-resolve-synergy_estimate"),
    );
    await waitFor(() =>
      expect(resolveSectionMock).toHaveBeenCalledWith(
        "s1",
        "synergy_estimate",
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("overview-bulk-resolve-toast")).toBeInTheDocument(),
    );
  });

  it("opens the panel for the clicked thread", async () => {
    getOverviewMock.mockResolvedValue(makeOverview());
    renderOverview();
    await waitFor(() => expect(screen.getByTestId("overview-thread-c1")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("overview-thread-c1"));
    await waitFor(() =>
      expect(screen.getByTestId("thread-panel")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("thread-anchor-label").textContent).toBe(
      "Section: synergy_estimate",
    );
  });
});
