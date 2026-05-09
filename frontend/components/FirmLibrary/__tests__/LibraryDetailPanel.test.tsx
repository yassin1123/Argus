import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LibraryDetailPanel from "../LibraryDetailPanel";

vi.mock("@/lib/api/firmLibrary", () => ({
  getFirmContent: vi.fn(),
  editFirmContent: vi.fn(),
  retireFirmContent: vi.fn(),
}));

import {
  editFirmContent,
  getFirmContent,
  retireFirmContent,
} from "@/lib/api/firmLibrary";

const mockedGet = getFirmContent as unknown as ReturnType<typeof vi.fn>;
const mockedEdit = editFirmContent as unknown as ReturnType<typeof vi.fn>;
const mockedRetire = retireFirmContent as unknown as ReturnType<typeof vi.fn>;

const FIRM_ID = "00000000-0000-0000-0000-000000000001";
const CONTENT_ID = "11111111-1111-1111-1111-111111111111";

function fc(overrides: Record<string, unknown> = {}) {
  return {
    firm_content: {
      id: CONTENT_ID,
      firm_id: FIRM_ID,
      title: "Sample Playbook",
      category: "playbook",
      description: "A standard target screen process.",
      intended_modes: ["due_diligence"],
      sector_tags: ["Fintech"],
      source_filename: "playbook.md",
      file_hash: "x",
      trust_level: "firm_vetted",
      uploaded_by: null,
      uploaded_at: "2026-05-09T00:00:00Z",
      retired_at: null,
      retired_by: null,
      chunk_count: 4,
      metadata: {},
      ...overrides,
    },
    chunk_preview: [
      {
        id: "ch1",
        content: "First chunk body.",
        position: 0,
        page: null,
        section_heading: "Intro",
        source_filename: "playbook.md",
      },
    ],
  };
}

afterEach(() => {
  cleanup();
  mockedGet.mockReset();
  mockedEdit.mockReset();
  mockedRetire.mockReset();
});

describe("LibraryDetailPanel", () => {
  it("renders the content and chunk preview for any member", async () => {
    mockedGet.mockResolvedValueOnce(fc());
    render(
      <LibraryDetailPanel
        firmId={FIRM_ID}
        contentId={CONTENT_ID}
        isAdmin={false}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText("Sample Playbook")).toBeInTheDocument();
    expect(screen.getByText("First chunk body.")).toBeInTheDocument();
    expect(screen.getByText(/4 chunks/)).toBeInTheDocument();
  });

  it("hides Edit and Retire buttons for non-admins", async () => {
    mockedGet.mockResolvedValueOnce(fc());
    render(
      <LibraryDetailPanel
        firmId={FIRM_ID}
        contentId={CONTENT_ID}
        isAdmin={false}
        onClose={() => {}}
      />,
    );
    await screen.findByText("Sample Playbook");
    expect(screen.queryByTestId("firm-library-edit-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("firm-library-retire-button")).not.toBeInTheDocument();
    expect(
      screen.getByText(/editing and retiring library content requires firm-admin access/i),
    ).toBeInTheDocument();
  });

  it("shows Edit and Retire buttons for admins", async () => {
    mockedGet.mockResolvedValueOnce(fc());
    render(
      <LibraryDetailPanel
        firmId={FIRM_ID}
        contentId={CONTENT_ID}
        isAdmin={true}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByTestId("firm-library-edit-button")).toBeInTheDocument();
    expect(screen.getByTestId("firm-library-retire-button")).toBeInTheDocument();
  });

  it("retires after the user confirms the dialog", async () => {
    mockedGet.mockResolvedValueOnce(fc());
    mockedRetire.mockResolvedValueOnce({
      firm_content: { ...fc().firm_content, retired_at: "2026-05-09T00:01:00Z" },
      already_retired: false,
    });

    const onMutated = vi.fn();
    render(
      <LibraryDetailPanel
        firmId={FIRM_ID}
        contentId={CONTENT_ID}
        isAdmin={true}
        onClose={() => {}}
        onMutated={onMutated}
      />,
    );

    const user = userEvent.setup();
    await user.click(await screen.findByTestId("firm-library-retire-button"));
    // Confirmation dialog appears.
    expect(
      screen.getByText(/excludes it from future retrieval but preserves historical citations/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /confirm retire/i }));

    await waitFor(() => expect(mockedRetire).toHaveBeenCalledTimes(1));
    expect(mockedRetire).toHaveBeenCalledWith(FIRM_ID, CONTENT_ID);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/retired\./i),
    );
    expect(onMutated).toHaveBeenCalledTimes(1);
  });

  it("submits an edit with the new fields", async () => {
    mockedGet.mockResolvedValueOnce(fc());
    mockedEdit.mockResolvedValueOnce({
      ...fc().firm_content,
      title: "Renamed Playbook",
      sector_tags: ["Fintech", "Payments"],
    });

    render(
      <LibraryDetailPanel
        firmId={FIRM_ID}
        contentId={CONTENT_ID}
        isAdmin={true}
        onClose={() => {}}
      />,
    );

    const user = userEvent.setup();
    await user.click(await screen.findByTestId("firm-library-edit-button"));

    const titleInput = screen.getByLabelText(/^title/i);
    await user.clear(titleInput);
    await user.type(titleInput, "Renamed Playbook");

    const sectorsInput = screen.getByLabelText(/sector tags/i);
    await user.clear(sectorsInput);
    await user.type(sectorsInput, "Fintech, Payments");

    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(mockedEdit).toHaveBeenCalledTimes(1));
    const [, , inputArg] = mockedEdit.mock.calls[0];
    expect(inputArg.title).toBe("Renamed Playbook");
    expect(inputArg.sectorTags).toEqual(["Fintech", "Payments"]);
  });

  it("calls onClose when the backdrop is clicked", async () => {
    mockedGet.mockResolvedValueOnce(fc());
    const onClose = vi.fn();
    render(
      <LibraryDetailPanel
        firmId={FIRM_ID}
        contentId={CONTENT_ID}
        isAdmin={false}
        onClose={onClose}
      />,
    );
    await screen.findByText("Sample Playbook");
    await userEvent.setup().click(screen.getByLabelText(/close detail panel/i));
    expect(onClose).toHaveBeenCalled();
  });
});
