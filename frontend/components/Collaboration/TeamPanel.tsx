"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  EngagementMember,
  EngagementRole,
  ROLE_LABEL,
  assignMember,
  changeMemberRole,
  listMembers,
  removeMember,
} from "@/lib/api/collaboration";

import UserAvatar from "./UserAvatar";

export interface FirmMemberOption {
  user_id: string;
  email?: string;
  full_name?: string;
}

interface Props {
  sessionId: string;
  /** Caller — used to determine whether to show management UI. */
  currentUserId: string;
  /** True when the caller is engagement lead OR firm admin. */
  canManage: boolean;
  /** Firm members eligible to be added to the engagement (already
   *  pre-filtered to members of the engagement's firm). The host
   *  fetches this once and passes it in so the panel doesn't have
   *  to re-fetch on every open. */
  firmMemberOptions?: FirmMemberOption[];
  /** Optional close handler when the host renders the panel as a
   *  modal/overlay. When omitted the panel renders inline. */
  onClose?: () => void;
  /** Fires after every mutation so the host can refresh coverage /
   *  badges. */
  onMutated?: () => void;
}

/**
 * W17/D4 team panel — replaces the W2-era workspace/TeamPanel for
 * the engagement-membership surface.
 *
 * Shows every active member with their W17 role badge. The reviewer
 * gets a distinct visual treatment (a "REVIEWER" pill in the
 * member's row) since they tie to W15's review workflow — the
 * spec calls out "shows the reviewer prominently".
 *
 * Lead/admin can:
 *   - Add a member (picker → role select → confirm)
 *   - Change role inline
 *   - Remove (soft — the service rejects lead removal w/o replacement)
 *
 * No drag-and-drop per W17/D4 hard rule — click-to-pick.
 */
export default function TeamPanel({
  sessionId,
  currentUserId,
  canManage,
  firmMemberOptions = [],
  onClose,
  onMutated,
}: Props) {
  const [members, setMembers] = useState<EngagementMember[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addPickerUser, setAddPickerUser] = useState<string>("");
  const [addPickerRole, setAddPickerRole] = useState<EngagementRole>("contributor");

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const data = await listMembers(sessionId);
      setMembers(data);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const memberUserIds = useMemo(
    () => new Set((members || []).map((m) => m.user_id)),
    [members],
  );
  const eligibleToAdd = useMemo(
    () => firmMemberOptions.filter((u) => !memberUserIds.has(u.user_id)),
    [firmMemberOptions, memberUserIds],
  );

  const handleAdd = async () => {
    if (!addPickerUser) return;
    setBusy(true);
    setError(null);
    try {
      await assignMember(sessionId, addPickerUser, addPickerRole);
      setAddPickerUser("");
      setAddPickerRole("contributor");
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleRoleChange = async (userId: string, role: EngagementRole) => {
    setBusy(true);
    setError(null);
    try {
      await changeMemberRole(sessionId, userId, role);
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (userId: string) => {
    if (!confirm("Remove this member from the engagement?")) return;
    setBusy(true);
    setError(null);
    try {
      await removeMember(sessionId, userId);
      await refresh();
      onMutated?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="team-panel"
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
            Engagement team
          </h2>
          <p style={{ margin: 0, fontSize: 11, color: "#6b7280" }}>
            Members and roles. The reviewer ties to the Week 15 review workflow.
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            data-testid="team-panel-close"
            aria-label="Close"
            style={{
              background: "transparent",
              border: 0,
              fontSize: 18,
              cursor: "pointer",
              color: "#6b7280",
            }}
          >
            ×
          </button>
        )}
      </header>

      {error && (
        <div
          data-testid="team-panel-error"
          style={{
            padding: "6px 8px",
            background: "#fee2e2",
            color: "#991b1b",
            borderRadius: 6,
            fontSize: 12,
            border: "1px solid #fecaca",
          }}
        >
          {error}
        </div>
      )}

      <ul style={{ listStyle: "none", margin: 0, padding: 0,
                    display: "flex", flexDirection: "column", gap: 6 }}>
        {members === null && (
          <li style={{ color: "#6b7280", fontSize: 12 }}>Loading…</li>
        )}
        {members && members.length === 0 && (
          <li data-testid="team-panel-empty" style={{ color: "#6b7280", fontSize: 12 }}>
            No members yet.
          </li>
        )}
        {members?.map((m) => (
          <MemberRow
            key={m.id}
            member={m}
            currentUserId={currentUserId}
            canManage={canManage}
            optionLabel={_findLabel(m, firmMemberOptions)}
            busy={busy}
            onRoleChange={handleRoleChange}
            onRemove={handleRemove}
          />
        ))}
      </ul>

      {canManage && (
        <div
          data-testid="team-panel-add"
          style={{
            borderTop: "1px solid #e5e7eb",
            paddingTop: 10,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <label style={{ fontSize: 11, color: "#6b7280" }}>Add member</label>
          <div style={{ display: "flex", gap: 6 }}>
            <select
              value={addPickerUser}
              onChange={(e) => setAddPickerUser(e.target.value)}
              data-testid="team-panel-add-user"
              disabled={busy || eligibleToAdd.length === 0}
              style={{ flex: 1, padding: "4px 6px", fontSize: 12 }}
            >
              <option value="">— pick firm member —</option>
              {eligibleToAdd.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.full_name || u.email || u.user_id.slice(0, 8)}
                </option>
              ))}
            </select>
            <select
              value={addPickerRole}
              onChange={(e) => setAddPickerRole(e.target.value as EngagementRole)}
              data-testid="team-panel-add-role"
              disabled={busy}
              style={{ padding: "4px 6px", fontSize: 12 }}
            >
              {(["contributor", "reviewer", "observer", "lead"] as EngagementRole[]).map((r) => (
                <option key={r} value={r}>{ROLE_LABEL[r]}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleAdd}
              disabled={busy || !addPickerUser}
              data-testid="team-panel-add-submit"
              style={{
                padding: "4px 10px",
                background: addPickerUser ? "#111827" : "#9ca3af",
                color: "white",
                border: 0,
                borderRadius: 4,
                fontSize: 12,
                cursor: addPickerUser ? "pointer" : "not-allowed",
              }}
            >
              Add
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------


function _findLabel(
  member: EngagementMember, options: FirmMemberOption[],
): { name: string; email: string } {
  const opt = options.find((o) => o.user_id === member.user_id);
  return {
    name: opt?.full_name || "",
    email: opt?.email || "",
  };
}

interface MemberRowProps {
  member: EngagementMember;
  currentUserId: string;
  canManage: boolean;
  optionLabel: { name: string; email: string };
  busy: boolean;
  onRoleChange: (userId: string, role: EngagementRole) => void;
  onRemove: (userId: string) => void;
}

function MemberRow({
  member,
  currentUserId,
  canManage,
  optionLabel,
  busy,
  onRoleChange,
  onRemove,
}: MemberRowProps) {
  const isSelf = member.user_id === currentUserId;
  const isReviewer = member.role === "reviewer";
  return (
    <li
      data-testid={`team-member-${member.user_id}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 8px",
        background: isReviewer ? "#fef9c3" : "transparent",
        border: isReviewer ? "1px solid #facc15" : "1px solid #e5e7eb",
        borderRadius: 6,
      }}
    >
      <UserAvatar
        name={optionLabel.name}
        email={optionLabel.email}
        size={26}
        roleBadge={member.role[0].toUpperCase()}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "#111827",
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>
          {optionLabel.name || optionLabel.email || member.user_id.slice(0, 8)}
          {isSelf && <span style={{ color: "#6b7280" }}> (you)</span>}
        </div>
        {optionLabel.email && (
          <div style={{ fontSize: 10, color: "#6b7280",
                         overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>
            {optionLabel.email}
          </div>
        )}
      </div>
      {isReviewer && (
        <span
          data-testid={`team-member-reviewer-badge-${member.user_id}`}
          style={{
            fontSize: 9,
            background: "#854d0e",
            color: "white",
            padding: "1px 5px",
            borderRadius: 3,
            fontWeight: 700,
            letterSpacing: 0.5,
          }}
        >
          REVIEWER
        </span>
      )}
      {canManage ? (
        <>
          <select
            value={member.role}
            onChange={(e) => onRoleChange(member.user_id, e.target.value as EngagementRole)}
            disabled={busy}
            data-testid={`team-member-role-${member.user_id}`}
            style={{ padding: "2px 4px", fontSize: 11 }}
          >
            {(["lead", "contributor", "reviewer", "observer"] as EngagementRole[]).map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => onRemove(member.user_id)}
            disabled={busy}
            data-testid={`team-member-remove-${member.user_id}`}
            style={{
              background: "transparent",
              border: 0,
              padding: 0,
              fontSize: 11,
              color: "#dc2626",
              cursor: "pointer",
            }}
          >
            Remove
          </button>
        </>
      ) : (
        <span
          data-testid={`team-member-role-${member.user_id}`}
          style={{
            padding: "2px 6px",
            background: "#f3f4f6",
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            fontSize: 11,
            color: "#374151",
            fontWeight: 500,
          }}
        >
          {ROLE_LABEL[member.role]}
        </span>
      )}
    </li>
  );
}
