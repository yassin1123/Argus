"use client";

import { useEffect, useMemo, useState } from "react";

import ModeEditPanel, { type EditPanelMode } from "@/components/FirmModes/ModeEditPanel";
import ModeList from "@/components/FirmModes/ModeList";
import { getCurrentUser, type AuthUser } from "@/lib/api";
import { listFirmModes, type ModeListItem } from "@/lib/api/firmModes";

// Phase 2 / Week 6 / Day 3 — firm-mode admin page.
// Members can read; admins can mutate. Server enforces the same gate.
export default function FirmModesPage() {
  const [user, setUser] = useState<AuthUser | null | "loading">("loading");
  const [refreshKey, setRefreshKey] = useState(0);
  const [panelMode, setPanelMode] = useState<EditPanelMode | null>(null);
  const [builtInNames, setBuiltInNames] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const u = await getCurrentUser();
      if (alive) setUser(u);
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Pull the built-in name list once for the base_mode dropdown in the panel.
  useEffect(() => {
    if (!user || user === "loading" || !user.default_firm_id) return;
    let alive = true;
    void (async () => {
      try {
        const items = await listFirmModes(user.default_firm_id!, { includeRetired: false });
        if (!alive) return;
        setBuiltInNames(items.filter((i) => i.is_builtin).map((i) => i.name));
      } catch {
        if (alive) setBuiltInNames([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [user, refreshKey]);

  if (user === "loading") {
    return (
      <main className="mx-auto max-w-[1100px] px-8 py-8">
        <p className="text-[13px] text-argus-tertiary">Loading…</p>
      </main>
    );
  }
  if (!user) {
    return (
      <main className="mx-auto max-w-[1100px] px-8 py-8">
        <p className="text-[13px] text-argus-contested">Sign in required.</p>
      </main>
    );
  }
  if (!user.default_firm_id) {
    return (
      <main className="mx-auto max-w-[1100px] px-8 py-8">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">
          Consulting modes
        </h1>
        <p className="mt-2 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
          Your account isn&apos;t associated with a firm yet. Ask an admin to add
          you to a firm before customising modes.
        </p>
      </main>
    );
  }

  const isAdmin = user.default_firm_role === "admin";
  const onMutated = () => setRefreshKey((k) => k + 1);

  return (
    <main className="mx-auto max-w-[1100px] px-8 py-8">
      <header className="mb-6 flex items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-[28px] font-semibold text-argus-primary">
            Consulting modes
          </h1>
          <p className="mt-1 text-[13px] text-argus-tertiary">
            Built-in modes ship with Argus. Firm admins can override or
            define new modes — required research branches, source
            priorities, trust rules, and writer / planner overlays.
          </p>
        </div>
        <span
          className={`rounded-sm border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
            isAdmin
              ? "border-argus-firm-border bg-argus-firm-bg text-argus-firm"
              : "border-argus-border-subtle bg-elevated text-argus-tertiary"
          }`}
          data-testid="firm-role-badge"
        >
          {isAdmin ? "Firm admin" : "Member"}
        </span>
      </header>

      <ModeList
        firmId={user.default_firm_id}
        refreshKey={refreshKey}
        onSelect={(item: ModeListItem) =>
          setPanelMode({ kind: "open_existing", name: item.name })
        }
        onCreateFresh={() => setPanelMode({ kind: "create_fresh" })}
        isAdmin={isAdmin}
      />

      {panelMode ? (
        <ModeEditPanel
          firmId={user.default_firm_id}
          isAdmin={isAdmin}
          builtInNames={builtInNames}
          panelMode={panelMode}
          onClose={() => setPanelMode(null)}
          onMutated={onMutated}
        />
      ) : null}
    </main>
  );
}
