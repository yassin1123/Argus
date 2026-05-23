import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import SectionOwnershipOverlay from "../SectionOwnershipOverlay";

const MEMBERS = [
  { user_id: "u-alex", full_name: "Alex Chen", email: "alex@m.invalid" },
  { user_id: "u-sarah", full_name: "Sarah Kim", email: "sarah@m.invalid" },
];

describe("SectionOwnershipOverlay", () => {
  it("renders an unassigned placeholder + status badge when no owner", () => {
    render(
      <SectionOwnershipOverlay
        sectionPath="synergy_estimate"
        owner={null}
        status="not_started"
        canManage
        canChangeStatus={false}
        memberOptions={MEMBERS}
        onAssign={() => {}}
        onChangeStatus={() => {}}
      />,
    );
    expect(
      screen.getByTestId("section-owner-unassigned-synergy_estimate"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("section-status-synergy_estimate").textContent)
      .toBe("Not started");
  });

  it("renders owner avatar + status when assigned", () => {
    render(
      <SectionOwnershipOverlay
        sectionPath="synergy_estimate"
        owner={MEMBERS[0]}
        status="in_progress"
        canManage
        canChangeStatus
        memberOptions={MEMBERS}
        onAssign={() => {}}
        onChangeStatus={() => {}}
      />,
    );
    expect(screen.getByTestId("section-owner-synergy_estimate")).toBeInTheDocument();
    expect(screen.getByTestId("section-status-synergy_estimate").textContent)
      .toBe("In progress");
  });

  it("lead clicks owner avatar → picker opens; selecting fires onAssign", () => {
    const onAssign = vi.fn();
    render(
      <SectionOwnershipOverlay
        sectionPath="synergy_estimate"
        owner={MEMBERS[0]}
        status="in_progress"
        canManage
        canChangeStatus={false}
        memberOptions={MEMBERS}
        onAssign={onAssign}
        onChangeStatus={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("section-owner-synergy_estimate"));
    expect(
      screen.getByTestId("section-owner-picker-synergy_estimate"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("section-owner-option-u-sarah"));
    expect(onAssign).toHaveBeenCalledWith("synergy_estimate", "u-sarah");
  });

  it("owner clicks status badge → picker; selecting fires onChangeStatus", () => {
    const onChangeStatus = vi.fn();
    render(
      <SectionOwnershipOverlay
        sectionPath="synergy_estimate"
        owner={MEMBERS[0]}
        status="in_progress"
        canManage={false}
        canChangeStatus
        memberOptions={MEMBERS}
        onAssign={() => {}}
        onChangeStatus={onChangeStatus}
      />,
    );
    fireEvent.click(screen.getByTestId("section-status-synergy_estimate"));
    expect(
      screen.getByTestId("section-status-picker-synergy_estimate"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("section-status-option-done"));
    expect(onChangeStatus).toHaveBeenCalledWith("synergy_estimate", "done");
  });

  it("non-manager + non-status-changer: badges render but are not interactive", () => {
    const onAssign = vi.fn();
    const onChangeStatus = vi.fn();
    render(
      <SectionOwnershipOverlay
        sectionPath="synergy_estimate"
        owner={MEMBERS[0]}
        status="done"
        canManage={false}
        canChangeStatus={false}
        memberOptions={MEMBERS}
        onAssign={onAssign}
        onChangeStatus={onChangeStatus}
      />,
    );
    // Click on the status badge — should NOT open a picker.
    fireEvent.click(screen.getByTestId("section-status-synergy_estimate"));
    expect(
      screen.queryByTestId("section-status-picker-synergy_estimate"),
    ).toBeNull();
    expect(onChangeStatus).not.toHaveBeenCalled();
  });
});
