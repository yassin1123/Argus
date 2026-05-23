import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { CommentRow, MentionsResponse } from "@/lib/api/comments";

vi.mock("@/lib/api/comments", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/comments")>(
    "@/lib/api/comments",
  );
  return { ...actual, listMyMentions: vi.fn() };
});

import MyMentions from "../MyMentions";
import { listMyMentions } from "@/lib/api/comments";

const listMyMentionsMock = listMyMentions as unknown as ReturnType<typeof vi.fn>;

function makeMention(overrides: Partial<CommentRow> = {}): CommentRow {
  const now = new Date().toISOString();
  return {
    id: "c-mention",
    session_id: "s1",
    firm_id: "f1",
    parent_comment_id: null,
    anchor_type: "engagement",
    anchor_ref: {},
    body: "Hey @sarah.kim — please review.",
    mentioned_user_ids: ["u-sarah"],
    author_id: "u-alex",
    resolved: false,
    resolved_by: null,
    resolved_at: null,
    created_at: now,
    updated_at: now,
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

function makeResponse(mentions: CommentRow[]): MentionsResponse {
  return {
    user_id: "u-sarah",
    firm_id: "f1",
    mentions,
    total: mentions.length,
  };
}

describe("MyMentions", () => {
  beforeEach(() => {
    listMyMentionsMock.mockReset();
  });

  it("lists mentions for the current user", async () => {
    listMyMentionsMock.mockResolvedValue(makeResponse([makeMention()]));
    render(<MyMentions userId="u-sarah" />);
    await waitFor(() =>
      expect(screen.getByTestId("my-mention-c-mention")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("my-mentions-total").textContent).toContain(
      "1 total",
    );
  });

  it("highlights mentions newer than the unread cutoff", async () => {
    const oldIso = new Date("2024-01-01").toISOString();
    const newIso = new Date("2026-05-23").toISOString();
    listMyMentionsMock.mockResolvedValue(
      makeResponse([
        makeMention({ id: "c-old", created_at: oldIso }),
        makeMention({ id: "c-new", created_at: newIso }),
      ]),
    );
    render(<MyMentions userId="u-sarah" unreadSince="2026-01-01T00:00:00Z" />);
    await waitFor(() =>
      expect(screen.getByTestId("my-mention-c-new")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("my-mention-c-new").getAttribute("data-unread"),
    ).toBe("true");
    expect(
      screen.getByTestId("my-mention-c-old").getAttribute("data-unread"),
    ).toBe("false");
  });

  it("re-fetches with unresolved_only=true when the toggle flips", async () => {
    listMyMentionsMock.mockResolvedValue(makeResponse([makeMention()]));
    render(<MyMentions userId="u-sarah" />);
    await waitFor(() => expect(listMyMentionsMock).toHaveBeenCalled());
    listMyMentionsMock.mockClear();
    fireEvent.click(screen.getByTestId("my-mentions-unresolved-only"));
    await waitFor(() =>
      expect(listMyMentionsMock).toHaveBeenCalledWith("u-sarah", {
        unresolved_only: true,
      }),
    );
  });

  it("calls onSelect when a mention row is clicked", async () => {
    listMyMentionsMock.mockResolvedValue(makeResponse([makeMention()]));
    const onSelect = vi.fn();
    render(<MyMentions userId="u-sarah" onSelect={onSelect} />);
    await waitFor(() =>
      expect(screen.getByTestId("my-mention-c-mention")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("my-mention-c-mention"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].id).toBe("c-mention");
  });
});
