import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ModeEditPanel from "../ModeEditPanel";

vi.mock("@/lib/api/firmModes", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/firmModes")>(
    "@/lib/api/firmModes",
  );
  return {
    ...actual,
    getFirmMode: vi.fn(),
    createFirmMode: vi.fn(),
    updateFirmMode: vi.fn(),
    retireFirmMode: vi.fn(),
  };
});

import {
  type FirmMode,
  type ResolvedMode,
  createFirmMode,
  getFirmMode,
  retireFirmMode,
  updateFirmMode,
} from "@/lib/api/firmModes";

const mockedGet = getFirmMode as unknown as ReturnType<typeof vi.fn>;
const mockedCreate = createFirmMode as unknown as ReturnType<typeof vi.fn>;
const mockedUpdate = updateFirmMode as unknown as ReturnType<typeof vi.fn>;
const mockedRetire = retireFirmMode as unknown as ReturnType<typeof vi.fn>;

const FIRM_ID = "11111111-1111-1111-1111-111111111111";
const BUILTINS = ["general", "market_entry", "due_diligence", "growth_strategy"];

function resolved(over: Partial<ResolvedMode> = {}): ResolvedMode {
  return {
    name: "market_entry",
    display_name: "Market entry",
    description: "",
    required_branches: ["market", "competition", "regulation"],
    reasoning_slots: [],
    source_priorities_default: [],
    trust_tier_rules: {},
    writer_overlay: "",
    planner_overlay: "",
    min_evidence_objects: 2,
    metadata: {},
    layer_provenance: {
      display_name: "built_in",
      description: "built_in",
      required_branches: "built_in",
      reasoning_slots: "built_in",
      source_priorities_default: "built_in",
      trust_tier_rules: "built_in",
      writer_overlay: "built_in",
      planner_overlay: "built_in",
    },
    ...over,
  };
}

function override(over: Partial<FirmMode> = {}): FirmMode {
  return {
    id: "fm",
    firm_id: FIRM_ID,
    name: "market_entry",
    base_mode: "market_entry",
    config: { display_name: "Firm A ME" },
    created_by: null,
    created_at: "",
    updated_at: "",
    retired_at: null,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ModeEditPanel", () => {
  it("renders all six configurable sections", async () => {
    mockedGet.mockResolvedValueOnce({
      name: "market_entry",
      resolved: resolved(),
      firm_override: null,
    });
    render(
      <ModeEditPanel
        firmId={FIRM_ID}
        isAdmin
        builtInNames={BUILTINS}
        panelMode={{ kind: "open_existing", name: "market_entry" }}
        onClose={() => {}}
        onMutated={() => {}}
      />,
    );
    await waitFor(() =>
      screen.getByText("Required branches", { exact: false }),
    );

    // Six sections present in the form.
    expect(screen.getByText("Display name")).toBeInTheDocument();
    expect(screen.getByText("Description")).toBeInTheDocument();
    expect(screen.getByText("Required branches")).toBeInTheDocument();
    expect(screen.getByText("Reasoning slots")).toBeInTheDocument();
    expect(screen.getByText("Source priorities (ordered)")).toBeInTheDocument();
    expect(screen.getByText("Trust tier rules")).toBeInTheDocument();
    expect(screen.getByText("Writer overlay")).toBeInTheDocument();
    expect(screen.getByText("Planner overlay")).toBeInTheDocument();
  });

  it("save calls createFirmMode when there's no existing override", async () => {
    mockedGet.mockResolvedValueOnce({
      name: "market_entry",
      resolved: resolved(),
      firm_override: null,
    });
    mockedCreate.mockResolvedValueOnce(override());
    const onMutated = vi.fn();
    render(
      <ModeEditPanel
        firmId={FIRM_ID}
        isAdmin
        builtInNames={BUILTINS}
        panelMode={{ kind: "open_existing", name: "market_entry" }}
        onClose={() => {}}
        onMutated={onMutated}
      />,
    );
    await waitFor(() => screen.getByText("Save override"));

    await userEvent.click(screen.getByText("Save override"));
    await waitFor(() => expect(mockedCreate).toHaveBeenCalledTimes(1));
    expect(mockedUpdate).not.toHaveBeenCalled();
    expect(onMutated).toHaveBeenCalled();

    const callArgs = mockedCreate.mock.calls[0];
    expect(callArgs[0]).toBe(FIRM_ID);
    expect(callArgs[1].name).toBe("market_entry");
    expect(callArgs[1].base_mode).toBe("market_entry");
  });

  it("save calls updateFirmMode when an override already exists", async () => {
    mockedGet.mockResolvedValueOnce({
      name: "market_entry",
      resolved: resolved(),
      firm_override: override(),
    });
    mockedUpdate.mockResolvedValueOnce(override({ config: { display_name: "v2" } }));
    render(
      <ModeEditPanel
        firmId={FIRM_ID}
        isAdmin
        builtInNames={BUILTINS}
        panelMode={{ kind: "open_existing", name: "market_entry" }}
        onClose={() => {}}
        onMutated={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("Save changes"));

    await userEvent.click(screen.getByText("Save changes"));
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1));
    expect(mockedCreate).not.toHaveBeenCalled();
    expect(mockedUpdate.mock.calls[0][1]).toBe("market_entry");
  });

  it("reset-to-default fires retireFirmMode after confirmation", async () => {
    mockedGet.mockResolvedValueOnce({
      name: "market_entry",
      resolved: resolved(),
      firm_override: override(),
    });
    mockedRetire.mockResolvedValueOnce(
      override({ retired_at: "2026-05-09T00:00:00Z" }),
    );
    render(
      <ModeEditPanel
        firmId={FIRM_ID}
        isAdmin
        builtInNames={BUILTINS}
        panelMode={{ kind: "open_existing", name: "market_entry" }}
        onClose={() => {}}
        onMutated={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("Reset to default"));

    await userEvent.click(screen.getByText("Reset to default"));
    // Confirmation modal opens.
    await waitFor(() => screen.getByRole("alertdialog"));
    await userEvent.click(screen.getByText("Reset to built-in"));

    await waitFor(() => expect(mockedRetire).toHaveBeenCalledTimes(1));
    expect(mockedRetire.mock.calls[0]).toEqual([FIRM_ID, "market_entry"]);
  });

  it("over-2000-char overlay turns the counter red and blocks save", async () => {
    mockedGet.mockResolvedValueOnce({
      name: "market_entry",
      resolved: resolved(),
      firm_override: null,
    });
    render(
      <ModeEditPanel
        firmId={FIRM_ID}
        isAdmin
        builtInNames={BUILTINS}
        panelMode={{ kind: "open_existing", name: "market_entry" }}
        onClose={() => {}}
        onMutated={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("Writer overlay"));

    const writerCounter = screen.getByTestId("writer-overlay-counter");
    expect(writerCounter.className).not.toContain("argus-contested");

    // Type 2001 chars via fireEvent (typing 2001 keys with userEvent is slow).
    const writerArea = screen.getAllByRole("textbox").find(
      (el) => el.id && (el as HTMLTextAreaElement).rows === 4,
    ) as HTMLTextAreaElement;
    expect(writerArea).toBeTruthy();

    const big = "x".repeat(2001);
    // Use change event for speed.
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(writerArea, { target: { value: big } });

    expect(writerCounter.className).toContain("argus-contested");

    // Save attempt surfaces the local validation error.
    await userEvent.click(screen.getByText("Save override"));
    await waitFor(() =>
      screen.getByText(/writer_overlay is 2001 chars/i),
    );
    expect(mockedCreate).not.toHaveBeenCalled();
  });
});
