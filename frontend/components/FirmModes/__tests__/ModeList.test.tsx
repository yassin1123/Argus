import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ModeList from "../ModeList";

vi.mock("@/lib/api/firmModes", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/firmModes")>(
    "@/lib/api/firmModes",
  );
  return {
    ...actual,
    listFirmModes: vi.fn(),
  };
});

import { listFirmModes, type ModeListItem } from "@/lib/api/firmModes";

const mockedList = listFirmModes as unknown as ReturnType<typeof vi.fn>;

const FIRM_ID = "11111111-1111-1111-1111-111111111111";

function modeItem(overrides: Partial<ModeListItem> & { name: string }): ModeListItem {
  return {
    is_builtin: true,
    has_firm_override: false,
    firm_override: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  mockedList.mockReset();
});

describe("ModeList", () => {
  it("renders cards with name + state badge", async () => {
    mockedList.mockResolvedValueOnce([
      modeItem({ name: "general", is_builtin: true, has_firm_override: false }),
      modeItem({
        name: "market_entry",
        is_builtin: true,
        has_firm_override: true,
        firm_override: {
          id: "x",
          firm_id: FIRM_ID,
          name: "market_entry",
          base_mode: "market_entry",
          config: { display_name: "Firm A ME" },
          created_by: null,
          created_at: "",
          updated_at: "",
          retired_at: null,
        },
      }),
    ]);
    render(
      <ModeList firmId={FIRM_ID} refreshKey={0} onSelect={() => {}} onCreateFresh={() => {}} isAdmin />,
    );
    await waitFor(() => screen.getByTestId("mode-card-general"));

    // Both cards present.
    expect(screen.getByTestId("mode-card-general")).toBeInTheDocument();
    expect(screen.getByTestId("mode-card-market_entry")).toBeInTheDocument();

    // Customised card carries the customised badge.
    const meCard = screen.getByTestId("mode-card-market_entry");
    expect(meCard.querySelector("[data-testid='mode-state-badge']")?.textContent).toBe(
      "Built-in customised",
    );
    // Display name from override surfaces.
    expect(meCard.textContent).toContain("Firm A ME");
  });

  it("filters cards by state via the state-filter tabs", async () => {
    mockedList.mockResolvedValueOnce([
      modeItem({ name: "general", is_builtin: true, has_firm_override: false }),
      modeItem({
        name: "market_entry",
        is_builtin: true,
        has_firm_override: true,
        firm_override: {
          id: "x",
          firm_id: FIRM_ID,
          name: "market_entry",
          base_mode: "market_entry",
          config: {},
          created_by: null,
          created_at: "",
          updated_at: "",
          retired_at: null,
        },
      }),
    ]);
    render(
      <ModeList firmId={FIRM_ID} refreshKey={0} onSelect={() => {}} onCreateFresh={() => {}} isAdmin />,
    );
    await waitFor(() => screen.getByTestId("mode-card-general"));

    // Click "Customised" filter.
    const customisedTab = screen.getByRole("tab", { name: "Customised" });
    await userEvent.click(customisedTab);

    // general (untouched built-in) drops; market_entry (customised) stays.
    expect(screen.queryByTestId("mode-card-general")).toBeNull();
    expect(screen.getByTestId("mode-card-market_entry")).toBeInTheDocument();
  });

  it("clicking a card calls onSelect with that item", async () => {
    mockedList.mockResolvedValueOnce([
      modeItem({ name: "general" }),
    ]);
    const onSelect = vi.fn();
    render(
      <ModeList firmId={FIRM_ID} refreshKey={0} onSelect={onSelect} onCreateFresh={() => {}} isAdmin />,
    );
    await waitFor(() => screen.getByTestId("mode-card-general"));
    await userEvent.click(screen.getByTestId("mode-card-general"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ name: "general" }));
  });

  it("create-custom button only renders for admin", async () => {
    // Admin sees the button.
    mockedList.mockResolvedValueOnce([modeItem({ name: "general" })]);
    render(
      <ModeList firmId={FIRM_ID} refreshKey={0} onSelect={() => {}} onCreateFresh={() => {}} isAdmin />,
    );
    await waitFor(() => screen.getByText("+ Create custom mode"));
    cleanup();

    // Non-admin doesn't.
    mockedList.mockResolvedValueOnce([modeItem({ name: "general" })]);
    render(
      <ModeList
        firmId={FIRM_ID}
        refreshKey={0}
        onSelect={() => {}}
        onCreateFresh={() => {}}
        isAdmin={false}
      />,
    );
    await waitFor(() => screen.getByTestId("mode-card-general"));
    expect(screen.queryByText("+ Create custom mode")).toBeNull();
  });
});
