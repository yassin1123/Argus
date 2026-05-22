import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  listEngagementMembers: vi.fn(),
}));

vi.mock("@/lib/api/review", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/review")>(
    "@/lib/api/review",
  );
  return { ...actual, submitForReview: vi.fn() };
});

import SubmitForReviewModal from "../SubmitForReviewModal";
import { listEngagementMembers } from "@/lib/api";
import { submitForReview } from "@/lib/api/review";

const listMembersMock = listEngagementMembers as ReturnType<typeof vi.fn>;
const submitMock = submitForReview as ReturnType<typeof vi.fn>;

describe("SubmitForReviewModal", () => {
  beforeEach(() => {
    listMembersMock.mockReset();
    submitMock.mockReset();
  });

  const team = [
    { user_id: "u-self", email: "self@meridian.invalid", full_name: "Self User", role: "lead" as const },
    { user_id: "u-admin", email: "admin@meridian.invalid", full_name: "Admin Voss", role: "member" as const },
    { user_id: "u-mate", email: "mate@meridian.invalid", full_name: "Marc Mate", role: "member" as const },
  ];

  it("excludes self from the reviewer picker by default", async () => {
    listMembersMock.mockResolvedValue(team);
    render(
      <SubmitForReviewModal
        sessionId="sess-1"
        currentUserId="u-self"
        onSubmitted={() => {}}
        onCancel={() => {}}
      />,
    );
    await waitFor(() => screen.getByTestId("reviewer-picker"));
    const picker = screen.getByTestId("reviewer-picker") as HTMLSelectElement;
    const options = Array.from(picker.querySelectorAll("option")).map(
      (o) => (o as HTMLOptionElement).value,
    );
    // First option is the open-pool empty value, followed by the eligible reviewers.
    expect(options).toEqual(["", "u-admin", "u-mate"]);
    expect(options).not.toContain("u-self");
  });

  it("includes self when allow_self_approval is true", async () => {
    listMembersMock.mockResolvedValue(team);
    render(
      <SubmitForReviewModal
        sessionId="sess-1"
        currentUserId="u-self"
        allowSelfApproval
        onSubmitted={() => {}}
        onCancel={() => {}}
      />,
    );
    await waitFor(() => screen.getByTestId("reviewer-picker"));
    const picker = screen.getByTestId("reviewer-picker") as HTMLSelectElement;
    const options = Array.from(picker.querySelectorAll("option")).map(
      (o) => (o as HTMLOptionElement).value,
    );
    expect(options).toContain("u-self");
  });

  it("fires submitForReview with the picked reviewer_id on confirm", async () => {
    listMembersMock.mockResolvedValue(team);
    submitMock.mockResolvedValue({
      session_id: "sess-1",
      from_state: "draft",
      to_state: "in_review",
      action: "submit_for_review",
      review_record_id: "rr-1",
      reviewer_id: "u-mate",
      artifacts_marked_stale: 0,
    });
    const onSubmitted = vi.fn();
    render(
      <SubmitForReviewModal
        sessionId="sess-1"
        currentUserId="u-self"
        onSubmitted={onSubmitted}
        onCancel={() => {}}
      />,
    );
    await waitFor(() => screen.getByTestId("reviewer-picker"));
    fireEvent.change(screen.getByTestId("reviewer-picker"), { target: { value: "u-mate" } });
    fireEvent.click(screen.getByTestId("submit-confirm"));
    await waitFor(() => {
      expect(submitMock).toHaveBeenCalledWith("sess-1", { reviewer_id: "u-mate" });
    });
    expect(onSubmitted).toHaveBeenCalled();
  });

  it("surfaces a clear hint when the engagement has no eligible reviewers", async () => {
    listMembersMock.mockResolvedValue([
      { user_id: "u-self", email: "x@y", full_name: "S", role: "lead" as const },
    ]);
    render(
      <SubmitForReviewModal
        sessionId="sess-1"
        currentUserId="u-self"
        onSubmitted={() => {}}
        onCancel={() => {}}
      />,
    );
    await waitFor(() => screen.getByTestId("no-eligible-reviewer"));
    expect(screen.getByTestId("no-eligible-reviewer")).toHaveTextContent(/no eligible reviewer/i);
  });
});
