import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/comments", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/comments")>(
    "@/lib/api/comments",
  );
  return {
    ...actual,
    getCounts: vi.fn(),
    listThreads: vi.fn(),
  };
});

import CommentsController from "../CommentsController";
import ClaimCommentAffordance from "../ClaimCommentAffordance";
import { getCounts, listThreads } from "@/lib/api/comments";

const getCountsMock = getCounts as unknown as ReturnType<typeof vi.fn>;
const listThreadsMock = listThreads as unknown as ReturnType<typeof vi.fn>;

describe("ClaimCommentAffordance", () => {
  beforeEach(() => {
    getCountsMock.mockReset();
    listThreadsMock.mockReset();
    getCountsMock.mockResolvedValue({
      by_anchor_type: {},
      by_section_path: {},
      unresolved_total: 0,
      total: 0,
    });
    listThreadsMock.mockResolvedValue({ session_id: "s1", threads: [], total: 0 });
  });

  it("opens a claim-anchored thread panel when clicked", async () => {
    render(
      <CommentsController
        sessionId="s1"
        currentUserId="u-alex"
        firmMembers={[
          { user_id: "u-alex", email: "alex.chen@m.invalid", full_name: "Alex" },
        ]}
        canComment
      >
        <ClaimCommentAffordance claimId="claim_kgr_1" />
      </CommentsController>,
    );

    // Panel hidden initially.
    expect(screen.queryByTestId("thread-panel")).toBeNull();

    fireEvent.click(screen.getByTestId("claim-comment-claim_kgr_1"));

    await waitFor(() =>
      expect(screen.getByTestId("thread-panel")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("thread-anchor-label").textContent).toBe(
      "claim: claim_kgr_1",
    );
  });

  it("returns null when rendered outside CommentsController", () => {
    // Defensive contract: deepening previews / standalone tests mount
    // SchemaDrivenSection without the controller. The affordance must
    // not crash in that environment.
    const { container } = render(<ClaimCommentAffordance claimId="claim_x" />);
    expect(container.firstChild).toBeNull();
  });
});
