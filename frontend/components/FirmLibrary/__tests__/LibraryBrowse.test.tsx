import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LibraryBrowse from "../LibraryBrowse";

vi.mock("@/lib/api/firmLibrary", () => ({
  listFirmContent: vi.fn(),
}));

import { listFirmContent } from "@/lib/api/firmLibrary";
import type { FirmContent, FirmContentCategory } from "@/lib/api/firmLibrary";

const mockedList = listFirmContent as unknown as ReturnType<typeof vi.fn>;

const FIRM_ID = "00000000-0000-0000-0000-000000000001";

function makeContent(
  overrides: Partial<FirmContent> & { id: string; title: string; category: FirmContentCategory },
): FirmContent {
  return {
    firm_id: FIRM_ID,
    description: null,
    intended_modes: [],
    sector_tags: [],
    source_filename: "x.md",
    file_hash: "x",
    trust_level: "firm_vetted",
    uploaded_by: null,
    uploaded_at: "2026-05-09T00:00:00Z",
    retired_at: null,
    retired_by: null,
    chunk_count: 5,
    metadata: {},
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  mockedList.mockReset();
});


describe("LibraryBrowse", () => {
  it("shows the empty state when the firm has no content", async () => {
    mockedList.mockResolvedValueOnce([]);
    render(<LibraryBrowse firmId={FIRM_ID} />);
    expect(await screen.findByTestId("firm-library-empty")).toBeInTheDocument();
    expect(screen.getByText(/no content yet/i)).toBeInTheDocument();
  });

  it("renders one card per content row with category, sectors, modes, chunk count", async () => {
    mockedList.mockResolvedValueOnce([
      makeContent({
        id: "c1",
        title: "M&A Target Screen",
        category: "playbook",
        intended_modes: ["due_diligence"],
        sector_tags: ["Payments", "Fintech"],
        chunk_count: 12,
      }),
      makeContent({
        id: "c2",
        title: "Retail Sector Primer",
        category: "sector_primer",
        sector_tags: ["Retail"],
        chunk_count: 24,
      }),
    ]);
    render(<LibraryBrowse firmId={FIRM_ID} />);

    expect(await screen.findByText("M&A Target Screen")).toBeInTheDocument();
    expect(screen.getByText("Retail Sector Primer")).toBeInTheDocument();
    // The chunk-count label appears formatted; check for "12 chunks" text.
    expect(screen.getByText(/12 chunks/)).toBeInTheDocument();
    expect(screen.getByText(/24 chunks/)).toBeInTheDocument();
    // Sector chips are rendered (also appear in the filter dropdown,
    // hence getAllByText — at least one match is enough to confirm
    // the chip rendered on the card).
    expect(screen.getAllByText("Payments").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fintech").length).toBeGreaterThan(0);
  });

  it("shows a Retired badge when retired_at is set", async () => {
    mockedList.mockResolvedValueOnce([
      makeContent({
        id: "c-retired",
        title: "Old methodology",
        category: "methodology",
        retired_at: "2026-04-01T12:00:00Z",
      }),
    ]);
    render(<LibraryBrowse firmId={FIRM_ID} />);
    expect(await screen.findByTestId("retired-badge")).toBeInTheDocument();
  });

  it("invokes onSelect with the row when a card is clicked", async () => {
    const onSelect = vi.fn();
    mockedList.mockResolvedValueOnce([
      makeContent({ id: "c1", title: "Open me", category: "playbook" }),
    ]);
    render(<LibraryBrowse firmId={FIRM_ID} onSelect={onSelect} />);

    const button = await screen.findByRole("button", { name: /open me/i });
    await userEvent.setup().click(button);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0]).toMatchObject({ id: "c1", title: "Open me" });
  });

  it("re-queries with the chosen filters and includes retired when status changes", async () => {
    const user = userEvent.setup();
    mockedList.mockResolvedValue([]); // initial fetch + every subsequent
    render(<LibraryBrowse firmId={FIRM_ID} />);

    // Initial fetch (status='active' → includeRetired=false).
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(1));
    expect(mockedList.mock.calls[0][1]).toMatchObject({ includeRetired: false });

    // Switch to retired-only.
    await user.selectOptions(screen.getByLabelText(/filter by status/i), "retired");
    await waitFor(() =>
      expect(
        mockedList.mock.calls.at(-1)?.[1],
      ).toMatchObject({ includeRetired: true }),
    );

    // Pick a category.
    await user.selectOptions(screen.getByLabelText(/filter by category/i), "playbook");
    await waitFor(() =>
      expect(mockedList.mock.calls.at(-1)?.[1]).toMatchObject({
        category: "playbook",
        includeRetired: true,
      }),
    );
  });
});
