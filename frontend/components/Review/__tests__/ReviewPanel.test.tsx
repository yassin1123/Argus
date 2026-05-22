import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/review", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/review")>(
    "@/lib/api/review",
  );
  return { ...actual, approveReview: vi.fn(), requestChanges: vi.fn() };
});

import ReviewPanel from "../ReviewPanel";
import { approveReview, requestChanges } from "@/lib/api/review";

const approveMock = approveReview as ReturnType<typeof vi.fn>;
const requestChangesMock = requestChanges as ReturnType<typeof vi.fn>;

const SECTIONS = ["recommendation", "synergy_estimate", "valuation_range", "risks"];

describe("ReviewPanel", () => {
  beforeEach(() => {
    approveMock.mockReset();
    requestChangesMock.mockReset();
  });

  it("does not render when ``visible`` is false (segregation of duties)", () => {
    const { container } = render(
      <ReviewPanel
        sessionId="s1"
        availableSectionPaths={SECTIONS}
        visible={false}
        onActed={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows approve + request-changes buttons in idle mode", () => {
    render(
      <ReviewPanel
        sessionId="s1"
        availableSectionPaths={SECTIONS}
        visible
        onActed={() => {}}
      />,
    );
    expect(screen.getByTestId("approve-open")).toBeInTheDocument();
    expect(screen.getByTestId("request-changes-open")).toBeInTheDocument();
  });

  it("approve flow requires confirmation then calls the API", async () => {
    approveMock.mockResolvedValue({});
    const onActed = vi.fn();
    render(
      <ReviewPanel
        sessionId="s1"
        availableSectionPaths={SECTIONS}
        visible
        onActed={onActed}
      />,
    );
    fireEvent.click(screen.getByTestId("approve-open"));
    expect(screen.getByTestId("approve-confirm")).toBeInTheDocument();
    expect(screen.getByTestId("approve-confirm")).toHaveTextContent(/lock the engagement/i);
    fireEvent.click(screen.getByTestId("approve-confirm-button"));
    await waitFor(() => expect(approveMock).toHaveBeenCalledWith("s1"));
    expect(onActed).toHaveBeenCalled();
  });

  it("request-changes form: overall note + add pointer + submit", async () => {
    requestChangesMock.mockResolvedValue({});
    const onActed = vi.fn();
    render(
      <ReviewPanel
        sessionId="s1"
        availableSectionPaths={SECTIONS}
        visible
        onActed={onActed}
      />,
    );
    fireEvent.click(screen.getByTestId("request-changes-open"));
    expect(screen.getByTestId("request-changes-form")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("overall-note"), {
      target: { value: "Tighten the synergy basis." },
    });
    fireEvent.change(screen.getByTestId("severity-select"), {
      target: { value: "blocking" },
    });

    // Add one pointer.
    fireEvent.click(screen.getByTestId("add-pointer"));
    fireEvent.change(screen.getByTestId("pointer-section-0"), {
      target: { value: "synergy_estimate" },
    });
    fireEvent.change(screen.getByTestId("pointer-severity-0"), {
      target: { value: "blocking" },
    });
    fireEvent.change(screen.getByTestId("pointer-note-0"), {
      target: { value: "Sourcing thin." },
    });

    fireEvent.click(screen.getByTestId("submit-changes"));
    await waitFor(() => expect(requestChangesMock).toHaveBeenCalled());
    const arg = requestChangesMock.mock.calls[0][1];
    expect(arg.overall_note).toBe("Tighten the synergy basis.");
    expect(arg.severity).toBe("blocking");
    expect(arg.section_pointers).toHaveLength(1);
    expect(arg.section_pointers[0]).toEqual({
      section_path: "synergy_estimate",
      note: "Sourcing thin.",
      severity: "blocking",
    });
    expect(onActed).toHaveBeenCalled();
  });

  it("blocks submit when overall note is empty", () => {
    render(
      <ReviewPanel
        sessionId="s1"
        availableSectionPaths={SECTIONS}
        visible
        onActed={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("request-changes-open"));
    fireEvent.click(screen.getByTestId("submit-changes"));
    expect(requestChangesMock).not.toHaveBeenCalled();
  });
});
