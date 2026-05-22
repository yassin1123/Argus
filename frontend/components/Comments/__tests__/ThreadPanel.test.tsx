import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { CommentRow, CommentThread } from "@/lib/api/comments";

vi.mock("@/lib/api/comments", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/comments")>(
    "@/lib/api/comments",
  );
  return {
    ...actual,
    listThreads: vi.fn(),
    createComment: vi.fn(),
    replyToComment: vi.fn(),
    resolveThread: vi.fn(),
    unresolveThread: vi.fn(),
    editComment: vi.fn(),
    deleteComment: vi.fn(),
  };
});

import ThreadPanel from "../ThreadPanel";
import {
  listThreads,
  replyToComment,
  resolveThread,
} from "@/lib/api/comments";

const listThreadsMock = listThreads as unknown as ReturnType<typeof vi.fn>;
const replyMock = replyToComment as unknown as ReturnType<typeof vi.fn>;
const resolveMock = resolveThread as unknown as ReturnType<typeof vi.fn>;

const _PARTNER_ID = "u-sarah";
const _CONSULTANT_ID = "u-alex";

const MEMBERS = [
  { user_id: _CONSULTANT_ID, email: "alex.chen@meridian.invalid", full_name: "Alex Chen" },
  { user_id: _PARTNER_ID, email: "sarah.kim@meridian.invalid", full_name: "Sarah Kim" },
];

function makeRoot(): CommentRow {
  return {
    id: "c-root",
    session_id: "s1",
    firm_id: "f1",
    parent_comment_id: null,
    anchor_type: "section",
    anchor_ref: { section_path: "synergy_estimate" },
    body: "Tighten the synergy basis.",
    mentioned_user_ids: [],
    author_id: _CONSULTANT_ID,
    resolved: false,
    resolved_by: null,
    resolved_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    edited_at: null,
    deleted_at: null,
  };
}

function makeReply(rootId: string): CommentRow {
  return {
    ...makeRoot(),
    id: "c-reply",
    parent_comment_id: rootId,
    body: "On it.",
    author_id: _PARTNER_ID,
  };
}

function makeThreadsResponse(threads: CommentThread[]) {
  return { session_id: "s1", threads, total: threads.length };
}

describe("ThreadPanel", () => {
  beforeEach(() => {
    listThreadsMock.mockReset();
    replyMock.mockReset();
    resolveMock.mockReset();
  });

  it("renders threads loaded from the API", async () => {
    const root = makeRoot();
    listThreadsMock.mockResolvedValue(
      makeThreadsResponse([
        { root, replies: [], resolved: false, orphaned: false },
      ]),
    );
    render(
      <ThreadPanel
        sessionId="s1"
        anchor={{
          anchor_type: "section",
          anchor_ref: { section_path: "synergy_estimate" },
          label: "synergy_estimate",
        }}
        currentUserId={_CONSULTANT_ID}
        firmMembers={MEMBERS}
        canComment
        onClose={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`thread-${root.id}`)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("thread-anchor-label").textContent).toBe(
      "synergy_estimate",
    );
  });

  it("fires the reply API when the user submits a reply", async () => {
    const root = makeRoot();
    listThreadsMock.mockResolvedValue(
      makeThreadsResponse([
        { root, replies: [], resolved: false, orphaned: false },
      ]),
    );
    replyMock.mockResolvedValue(makeReply(root.id));
    render(
      <ThreadPanel
        sessionId="s1"
        anchor={{
          anchor_type: "section",
          anchor_ref: { section_path: "synergy_estimate" },
          label: "synergy_estimate",
        }}
        currentUserId={_PARTNER_ID}
        firmMembers={MEMBERS}
        canComment
        onClose={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`thread-${root.id}`)).toBeInTheDocument(),
    );
    const replyInput = screen.getByTestId(
      `thread-reply-input-${root.id}`,
    ) as HTMLTextAreaElement;
    fireEvent.change(replyInput, { target: { value: "Reviewing now." } });
    fireEvent.click(screen.getByTestId(`thread-reply-submit-${root.id}`));
    await waitFor(() => expect(replyMock).toHaveBeenCalledTimes(1));
    expect(replyMock).toHaveBeenCalledWith(root.id, "Reviewing now.");
  });

  it("toggles resolution when the resolve button is clicked", async () => {
    const root = makeRoot();
    listThreadsMock.mockResolvedValue(
      makeThreadsResponse([
        { root, replies: [], resolved: false, orphaned: false },
      ]),
    );
    resolveMock.mockResolvedValue({
      ok: true,
      comment_id: root.id,
      resolved: true,
    });
    render(
      <ThreadPanel
        sessionId="s1"
        anchor={{
          anchor_type: "section",
          anchor_ref: { section_path: "synergy_estimate" },
          label: "synergy_estimate",
        }}
        currentUserId={_CONSULTANT_ID}
        firmMembers={MEMBERS}
        canComment
        onClose={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`thread-resolve-toggle-${root.id}`)).toHaveTextContent("Resolve"),
    );
    fireEvent.click(screen.getByTestId(`thread-resolve-toggle-${root.id}`));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith(root.id));
  });
});
