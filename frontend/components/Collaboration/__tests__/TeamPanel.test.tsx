import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { EngagementMember } from "@/lib/api/collaboration";

vi.mock("@/lib/api/collaboration", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/collaboration")>(
    "@/lib/api/collaboration",
  );
  return {
    ...actual,
    listMembers: vi.fn(),
    assignMember: vi.fn(),
    changeMemberRole: vi.fn(),
    removeMember: vi.fn(),
  };
});

import TeamPanel from "../TeamPanel";
import {
  assignMember,
  changeMemberRole,
  listMembers,
  removeMember,
} from "@/lib/api/collaboration";

const listMembersMock = listMembers as unknown as ReturnType<typeof vi.fn>;
const assignMemberMock = assignMember as unknown as ReturnType<typeof vi.fn>;
const changeRoleMock = changeMemberRole as unknown as ReturnType<typeof vi.fn>;
const removeMock = removeMember as unknown as ReturnType<typeof vi.fn>;

const _LEAD = "lead-user-id";
const _CONTRIB = "contrib-user-id";
const _PARTNER = "partner-user-id";

function makeMember(user_id: string, role: string): EngagementMember {
  return {
    id: `m-${user_id}`,
    session_id: "s1",
    firm_id: "f1",
    user_id,
    role: role as EngagementMember["role"],
    assigned_by: _LEAD,
    assigned_at: "2026-01-01T00:00:00Z",
    removed_at: null,
  };
}

const ALL = [
  makeMember(_LEAD, "lead"),
  makeMember(_CONTRIB, "contributor"),
  makeMember(_PARTNER, "reviewer"),
];

const FIRM_OPTIONS = [
  { user_id: _LEAD, full_name: "Helena Voss", email: "helena@m.invalid" },
  { user_id: _CONTRIB, full_name: "Marcus Thorne", email: "marcus@m.invalid" },
  { user_id: _PARTNER, full_name: "Sarah Kim", email: "sarah@m.invalid" },
  { user_id: "new-user", full_name: "New Person", email: "new@m.invalid" },
];

describe("TeamPanel", () => {
  beforeEach(() => {
    listMembersMock.mockReset();
    assignMemberMock.mockReset();
    changeRoleMock.mockReset();
    removeMock.mockReset();
  });

  it("renders members with the reviewer prominently flagged", async () => {
    listMembersMock.mockResolvedValue(ALL);
    render(
      <TeamPanel
        sessionId="s1"
        currentUserId={_LEAD}
        canManage
        firmMemberOptions={FIRM_OPTIONS}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`team-member-${_PARTNER}`)).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId(`team-member-reviewer-badge-${_PARTNER}`),
    ).toBeInTheDocument();
  });

  it("contributor cannot manage — no add/remove UI rendered", async () => {
    listMembersMock.mockResolvedValue(ALL);
    render(
      <TeamPanel
        sessionId="s1"
        currentUserId={_CONTRIB}
        canManage={false}
        firmMemberOptions={FIRM_OPTIONS}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`team-member-${_CONTRIB}`)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("team-panel-add")).toBeNull();
    expect(screen.queryByTestId(`team-member-remove-${_LEAD}`)).toBeNull();
  });

  it("lead can add a member via the picker", async () => {
    listMembersMock.mockResolvedValue(ALL);
    assignMemberMock.mockResolvedValue(makeMember("new-user", "contributor"));
    render(
      <TeamPanel
        sessionId="s1"
        currentUserId={_LEAD}
        canManage
        firmMemberOptions={FIRM_OPTIONS}
      />,
    );
    await waitFor(() => expect(screen.getByTestId("team-panel-add")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("team-panel-add-user"), {
      target: { value: "new-user" },
    });
    fireEvent.change(screen.getByTestId("team-panel-add-role"), {
      target: { value: "reviewer" },
    });
    fireEvent.click(screen.getByTestId("team-panel-add-submit"));
    await waitFor(() =>
      expect(assignMemberMock).toHaveBeenCalledWith(
        "s1", "new-user", "reviewer",
      ),
    );
  });

  it("lead can change a member's role inline", async () => {
    listMembersMock.mockResolvedValue(ALL);
    changeRoleMock.mockResolvedValue(makeMember(_CONTRIB, "observer"));
    render(
      <TeamPanel
        sessionId="s1"
        currentUserId={_LEAD}
        canManage
        firmMemberOptions={FIRM_OPTIONS}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`team-member-${_CONTRIB}`)).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId(`team-member-role-${_CONTRIB}`), {
      target: { value: "observer" },
    });
    await waitFor(() =>
      expect(changeRoleMock).toHaveBeenCalledWith("s1", _CONTRIB, "observer"),
    );
  });

  it("lead can remove a member with confirm", async () => {
    listMembersMock.mockResolvedValue(ALL);
    removeMock.mockResolvedValue({ ok: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <TeamPanel
        sessionId="s1"
        currentUserId={_LEAD}
        canManage
        firmMemberOptions={FIRM_OPTIONS}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId(`team-member-${_PARTNER}`)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId(`team-member-remove-${_PARTNER}`));
    await waitFor(() =>
      expect(removeMock).toHaveBeenCalledWith("s1", _PARTNER),
    );
  });
});
