import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/review", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/review")>(
    "@/lib/api/review",
  );
  return { ...actual, resolvePointer: vi.fn(), submitForReview: vi.fn() };
});

import ChangesRequestedPanel from "../ChangesRequestedPanel";
import { ReviewBlockedError, resolvePointer, submitForReview } from "@/lib/api/review";
import type { ReviewFeedback } from "@/lib/api/review";

const resolveMock = resolvePointer as ReturnType<typeof vi.fn>;
const submitMock = submitForReview as ReturnType<typeof vi.fn>;

const FB: ReviewFeedback = {
  overall_note: "Tighten the synergy + risks.",
  severity: "major",
  section_pointers: [
    {
      section_path: "synergy_estimate",
      note: "Sourcing thin.",
      severity: "major",
      resolved: false,
    },
    {
      section_path: "risks",
      note: "Add one more.",
      severity: "minor",
      resolved: false,
    },
  ],
};

describe("ChangesRequestedPanel", () => {
  beforeEach(() => {
    resolveMock.mockReset();
    submitMock.mockReset();
  });

  it("renders overall note + every pointer with its severity", () => {
    render(
      <ChangesRequestedPanel
        sessionId="s1"
        reviewRecordId="rr1"
        feedback={FB}
        onResolved={() => {}}
        onResubmitted={() => {}}
      />,
    );
    expect(screen.getByTestId("overall-feedback")).toHaveTextContent("Tighten");
    expect(screen.getByTestId("pointer-synergy_estimate")).toBeInTheDocument();
    expect(screen.getByTestId("pointer-risks")).toBeInTheDocument();
  });

  it("resubmit button is disabled while major/blocking pointers are unresolved", () => {
    render(
      <ChangesRequestedPanel
        sessionId="s1"
        reviewRecordId="rr1"
        feedback={FB}
        onResolved={() => {}}
        onResubmitted={() => {}}
      />,
    );
    const btn = screen.getByTestId("resubmit-button") as HTMLButtonElement;
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title")).toContain("synergy_estimate");
  });

  it("clicking 'Mark resolved' on the major pointer enables resubmit", async () => {
    resolveMock.mockResolvedValue({ review_record_id: "rr1", section_path: "synergy_estimate", changed: true });
    const onResolved = vi.fn();
    render(
      <ChangesRequestedPanel
        sessionId="s1"
        reviewRecordId="rr1"
        feedback={FB}
        onResolved={onResolved}
        onResubmitted={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("resolve-synergy_estimate"));
    await waitFor(() => {
      expect(resolveMock).toHaveBeenCalledWith("s1", "rr1", "synergy_estimate");
    });
    expect(onResolved).toHaveBeenCalled();
    // Resubmit is now enabled (minor pointer doesn't gate).
    expect(screen.getByTestId("resubmit-button")).not.toBeDisabled();
    expect(screen.getByTestId("resolved-synergy_estimate")).toBeInTheDocument();
  });

  it("server-side rejection of resubmit (409 with blocking paths) surfaces in the UI", async () => {
    // Construct a panel where the local state THINKS everything is
    // resolved (so the client-side gate doesn't block the click),
    // then the server returns a 409 anyway. This exercises the
    // ReviewBlockedError branch.
    const fbResolved: ReviewFeedback = {
      ...FB,
      section_pointers: FB.section_pointers.map((p) => ({ ...p, resolved: true })),
    };
    submitMock.mockRejectedValue(
      new ReviewBlockedError({
        reason: "resubmit blocked",
        blocking_pointer_paths: ["synergy_estimate"],
      }),
    );
    render(
      <ChangesRequestedPanel
        sessionId="s1"
        reviewRecordId="rr1"
        feedback={fbResolved}
        onResolved={() => {}}
        onResubmitted={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("resubmit-button"));
    await waitFor(() => {
      expect(screen.getByTestId("changes-error")).toHaveTextContent(/blocking/i);
    });
    expect(screen.getByTestId("changes-error")).toHaveTextContent("synergy_estimate");
  });

  it("jump-to-section calls onJumpToSection with the path", () => {
    const onJump = vi.fn();
    render(
      <ChangesRequestedPanel
        sessionId="s1"
        reviewRecordId="rr1"
        feedback={FB}
        onResolved={() => {}}
        onResubmitted={() => {}}
        onJumpToSection={onJump}
      />,
    );
    fireEvent.click(screen.getByTestId("jump-synergy_estimate"));
    expect(onJump).toHaveBeenCalledWith("synergy_estimate");
  });
});
