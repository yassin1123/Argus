"use client";

import { useState } from "react";

import {
  SectionStatus,
  STATUS_COLOR,
  STATUS_LABEL,
} from "@/lib/api/collaboration";

import UserAvatar from "./UserAvatar";

interface OwnerInfo {
  user_id: string;
  full_name?: string;
  email?: string;
}

interface Props {
  sectionPath: string;
  owner: OwnerInfo | null;
  status: SectionStatus;
  /** True when the viewing user can reassign the owner (lead/admin). */
  canManage: boolean;
  /** True when the viewing user can change status (owner/lead/admin). */
  canChangeStatus: boolean;
  /** Picker of engagement members for reassignment, supplied by the
   *  host so we don't re-fetch on every section. */
  memberOptions: OwnerInfo[];
  onAssign: (sectionPath: string, userId: string) => void | Promise<void>;
  onChangeStatus: (sectionPath: string, status: SectionStatus) => void | Promise<void>;
  onUnassign?: (sectionPath: string) => void | Promise<void>;
}

/**
 * Section-header overlay — owner avatar + status badge, with two
 * popover surfaces:
 *
 *   - Click the avatar (lead/admin) → owner picker.
 *   - Click the status badge (owner/lead/admin) → status picker.
 *
 * Sits LEFT of the W16 comment affordance in SectionWrapper's
 * top-right slot (the comment affordance is the more visually
 * dominant signal). Compact by design — the consultant should be
 * able to glance at any section header and see "owned by Sarah,
 * in progress" without slowing down their read.
 */
export default function SectionOwnershipOverlay({
  sectionPath,
  owner,
  status,
  canManage,
  canChangeStatus,
  memberOptions,
  onAssign,
  onChangeStatus,
  onUnassign,
}: Props) {
  const [openOwner, setOpenOwner] = useState(false);
  const [openStatus, setOpenStatus] = useState(false);

  const color = STATUS_COLOR[status];

  return (
    <span
      data-testid={`section-ownership-${sectionPath}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        position: "relative",
      }}
    >
      {/* Owner */}
      {owner ? (
        <UserAvatar
          name={owner.full_name}
          email={owner.email}
          size={22}
          onClick={canManage ? () => setOpenOwner((v) => !v) : undefined}
          testId={`section-owner-${sectionPath}`}
        />
      ) : (
        <button
          type="button"
          onClick={canManage ? () => setOpenOwner((v) => !v) : undefined}
          disabled={!canManage}
          data-testid={`section-owner-unassigned-${sectionPath}`}
          title={canManage ? "Assign an owner" : "Unassigned"}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 22,
            height: 22,
            borderRadius: "50%",
            border: "1px dashed #9ca3af",
            background: "transparent",
            color: "#6b7280",
            fontSize: 11,
            cursor: canManage ? "pointer" : "default",
          }}
        >
          ?
        </button>
      )}

      {/* Status badge */}
      <button
        type="button"
        onClick={canChangeStatus ? () => setOpenStatus((v) => !v) : undefined}
        disabled={!canChangeStatus}
        data-testid={`section-status-${sectionPath}`}
        style={{
          padding: "2px 6px",
          background: color.bg,
          border: `1px solid ${color.border}`,
          borderRadius: 4,
          color: color.fg,
          fontSize: 10,
          fontWeight: 600,
          cursor: canChangeStatus ? "pointer" : "default",
          textTransform: "uppercase",
          letterSpacing: 0.4,
        }}
      >
        {STATUS_LABEL[status]}
      </button>

      {/* Owner picker popover */}
      {openOwner && (
        <ul
          data-testid={`section-owner-picker-${sectionPath}`}
          role="listbox"
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: 4,
            background: "white",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            padding: 4,
            listStyle: "none",
            zIndex: 50,
            minWidth: 180,
          }}
        >
          {memberOptions.map((m) => (
            <li key={m.user_id}>
              <button
                type="button"
                onClick={async () => {
                  setOpenOwner(false);
                  await onAssign(sectionPath, m.user_id);
                }}
                data-testid={`section-owner-option-${m.user_id}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  width: "100%",
                  background: "transparent",
                  border: 0,
                  padding: "4px 6px",
                  borderRadius: 4,
                  cursor: "pointer",
                  textAlign: "left",
                  fontSize: 12,
                }}
              >
                <UserAvatar name={m.full_name} email={m.email} size={18} />
                <span>{m.full_name || m.email || m.user_id.slice(0, 8)}</span>
              </button>
            </li>
          ))}
          {owner && onUnassign && (
            <li style={{ borderTop: "1px solid #e5e7eb", marginTop: 4 }}>
              <button
                type="button"
                onClick={async () => {
                  setOpenOwner(false);
                  await onUnassign(sectionPath);
                }}
                data-testid={`section-owner-unassign-${sectionPath}`}
                style={{
                  width: "100%",
                  background: "transparent",
                  border: 0,
                  padding: "6px",
                  borderRadius: 4,
                  cursor: "pointer",
                  textAlign: "left",
                  fontSize: 12,
                  color: "#6b7280",
                }}
              >
                Unassign
              </button>
            </li>
          )}
        </ul>
      )}

      {/* Status picker popover */}
      {openStatus && (
        <ul
          data-testid={`section-status-picker-${sectionPath}`}
          role="listbox"
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: 4,
            background: "white",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            padding: 4,
            listStyle: "none",
            zIndex: 50,
            minWidth: 140,
          }}
        >
          {(["not_started", "in_progress", "needs_review", "done"] as SectionStatus[]).map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={async () => {
                  setOpenStatus(false);
                  await onChangeStatus(sectionPath, s);
                }}
                data-testid={`section-status-option-${s}`}
                style={{
                  display: "block",
                  width: "100%",
                  background: "transparent",
                  border: 0,
                  padding: "4px 6px",
                  borderRadius: 4,
                  cursor: "pointer",
                  textAlign: "left",
                  fontSize: 12,
                  color: STATUS_COLOR[s].fg,
                  fontWeight: s === status ? 700 : 400,
                }}
              >
                {STATUS_LABEL[s]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}
