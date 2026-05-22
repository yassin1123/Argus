import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { CommentRow } from "@/lib/api/comments";

vi.mock("@/lib/api/comments", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/comments")>(
    "@/lib/api/comments",
  );
  return { ...actual, listThreads: vi.fn() };
});

import ThreadPanel from "../ThreadPanel";
import { listThreads } from "@/lib/api/comments";

const listThreadsMock = listThreads as unknown as ReturnType<typeof vi.fn>;

function makeTextRangeRow(quotedText: string): CommentRow {
  return {
    id: "c-orphan",
    session_id: "s1",
    firm_id: "f1",
    parent_comment_id: null,
    anchor_type: "text_range",
    anchor_ref: {
      section_path: "synergy_estimate",
      start: 12,
      end: 34,
      quoted_text: quotedText,
    },
    body: "What's the source for this?",
    mentioned_user_ids: [],
    author_id: "u-alex",
    resolved: false,
    resolved_by: null,
    resolved_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    edited_at: null,
    deleted_at: null,
  };
}

describe("OrphanFlag", () => {
  beforeEach(() => {
    listThreadsMock.mockReset();
  });

  it("renders the orphan banner with the original quote when the thread is orphaned", async () => {
    const root = makeTextRangeRow("Cross-sell uplift of 5% in year two");
    listThreadsMock.mockResolvedValue({
      session_id: "s1",
      threads: [
        { root, replies: [], resolved: false, orphaned: true },
      ],
      total: 1,
    });
    render(
      <ThreadPanel
        sessionId="s1"
        anchor={{
          anchor_type: "text_range",
          anchor_ref: { section_path: "synergy_estimate" },
          label: "synergy_estimate",
        }}
        currentUserId="u-alex"
        firmMembers={[]}
        canComment
        onClose={() => {}}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId(`thread-orphan-flag-${root.id}`),
      ).toBeInTheDocument(),
    );
    const flag = screen.getByTestId(`thread-orphan-flag-${root.id}`);
    expect(flag.textContent).toContain("The text this refers to has changed");
    expect(flag.textContent).toContain("Cross-sell uplift of 5% in year two");
  });

  it("does NOT render the orphan banner when the thread is healthy", async () => {
    const root = makeTextRangeRow("Some quote.");
    listThreadsMock.mockResolvedValue({
      session_id: "s1",
      threads: [
        { root, replies: [], resolved: false, orphaned: false },
      ],
      total: 1,
    });
    render(
      <ThreadPanel
        sessionId="s1"
        anchor={{
          anchor_type: "text_range",
          anchor_ref: { section_path: "synergy_estimate" },
          label: "synergy_estimate",
        }}
        currentUserId="u-alex"
        firmMembers={[]}
        canComment
        onClose={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`thread-${root.id}`)).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId(`thread-orphan-flag-${root.id}`),
    ).toBeNull();
  });
});
