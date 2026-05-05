"use client";

import { useEffect, useState } from "react";

import {
  addEngagementMember,
  listEngagementMembers,
  removeEngagementMember,
} from "@/lib/api";
import type { EngagementMember, EngagementRole } from "@/lib/types";

const ROLE_TONE: Record<EngagementRole, string> = {
  lead: "bg-argus-firm-bg text-argus-firm border-argus-firm-border",
  member: "bg-argus-credible-bg text-argus-credible border-argus-credible-border",
  viewer: "bg-elevated text-argus-tertiary border-argus-border-subtle",
};

const ROLE_DESC: Record<EngagementRole, string> = {
  lead: "Read · write · manage members",
  member: "Read · write",
  viewer: "Read only · can export",
};

function CloseIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export default function TeamPanel({
  engagementId,
  canManage,
  open,
  onClose,
}: {
  engagementId: string;
  canManage: boolean;
  open: boolean;
  onClose: () => void;
}) {
  const [members, setMembers] = useState<EngagementMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Add-member form
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<EngagementRole>("member");

  const refresh = async () => {
    try {
      const list = await listEngagementMembers(engagementId);
      setMembers(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load members");
    }
  };

  useEffect(() => {
    if (!open) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, engagementId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await addEngagementMember(engagementId, email.trim(), role);
      setEmail("");
      setRole("member");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (userId: string) => {
    setBusy(true);
    setError(null);
    try {
      await removeEngagementMember(engagementId, userId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove member");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
      <aside
        role="dialog"
        aria-label="Engagement team"
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col overflow-hidden border-l border-argus-border-subtle bg-canvas shadow-argus-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-argus-border-subtle px-5 py-4">
          <div>
            <div className="argus-label">Engagement team</div>
            <h2 className="mt-1 font-serif text-[18px] font-semibold text-argus-primary">
              Members &amp; roles
            </h2>
            <p className="mt-1 text-[12px] leading-snug text-argus-tertiary">
              {canManage
                ? "Leads can invite teammates as members or viewers."
                : "Read-only view. Ask a lead to change roles."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-argus-sm p-1 text-argus-tertiary transition-colors hover:bg-elevated hover:text-argus-primary"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        {error ? (
          <p className="mx-5 mt-3 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
            {error}
          </p>
        ) : null}

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {!members ? (
            <p className="text-[12px] text-argus-tertiary">Loading members…</p>
          ) : members.length === 0 ? (
            <p className="text-[12px] text-argus-tertiary">No members yet.</p>
          ) : (
            <ul className="divide-y divide-argus-border-subtle">
              {members.map((m) => {
                const initials = (m.full_name || m.email)
                  .split(/\s+|@/)
                  .filter(Boolean)
                  .slice(0, 2)
                  .map((p) => p[0]?.toUpperCase() ?? "")
                  .join("") || "?";
                return (
                  <li key={m.user_id} className="flex items-center gap-3 py-2.5">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-argus-primary text-[10px] font-semibold text-argus-inverse">
                      {initials}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-serif text-[13px] font-medium text-argus-primary">
                        {m.full_name || m.email}
                      </div>
                      {m.full_name ? (
                        <div className="text-[11px] text-argus-tertiary">{m.email}</div>
                      ) : null}
                      <div className="text-[10px] text-argus-tertiary">{ROLE_DESC[m.role]}</div>
                    </div>
                    <span className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${ROLE_TONE[m.role]}`}>
                      {m.role}
                    </span>
                    {canManage ? (
                      <button
                        type="button"
                        onClick={() => void handleRemove(m.user_id)}
                        disabled={busy}
                        title="Remove from engagement"
                        className="ml-1 text-[10px] text-argus-tertiary hover:text-argus-contested disabled:opacity-40"
                      >
                        Remove
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {canManage ? (
          <form
            onSubmit={handleAdd}
            className="border-t border-argus-border-subtle bg-[var(--bg-rail)] p-4"
          >
            <div className="argus-label mb-2">Add member</div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                type="email"
                placeholder="email@firm.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="flex-1 rounded-sm border border-argus-border-moderate bg-surface px-2 py-1.5 text-[12px] text-argus-primary focus:border-argus-border-strong focus:outline-none"
              />
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as EngagementRole)}
                className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1.5 text-[12px] text-argus-primary focus:outline-none"
              >
                <option value="lead">Lead</option>
                <option value="member">Member</option>
                <option value="viewer">Viewer</option>
              </select>
              <button
                type="submit"
                disabled={busy || !email.trim()}
                className="rounded-sm border border-argus-border-strong bg-argus-primary px-3 py-1.5 text-[12px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "Adding…" : "Invite"}
              </button>
            </div>
            <p className="mt-2 text-[10px] text-argus-tertiary">
              The user must already have an Argus account. They&apos;ll see the engagement on their next login.
            </p>
          </form>
        ) : null}
      </aside>
    </>
  );
}
