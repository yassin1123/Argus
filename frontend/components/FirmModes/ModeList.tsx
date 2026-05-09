"use client";

import { useEffect, useMemo, useState } from "react";

import {
  type ModeListItem,
  listFirmModes,
  modeStateLabel,
} from "@/lib/api/firmModes";

export type ModeStateFilter = "all" | "built_in" | "customised" | "custom" | "retired";

const STATE_FILTERS: { value: ModeStateFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "built_in", label: "Built-ins" },
  { value: "customised", label: "Customised" },
  { value: "custom", label: "Custom" },
  { value: "retired", label: "Retired" },
];

const STATE_BADGE_CLASS: Record<string, string> = {
  "Built-in": "border-argus-border-subtle bg-elevated text-argus-secondary",
  "Built-in customised": "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  Custom: "border-argus-accent-border bg-argus-accent-bg text-argus-accent",
  Retired: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

export interface ModeListProps {
  firmId: string;
  refreshKey: number;
  onSelect: (item: ModeListItem) => void;
  onCreateFresh: () => void;
  isAdmin: boolean;
}

export default function ModeList({
  firmId,
  refreshKey,
  onSelect,
  onCreateFresh,
  isAdmin,
}: ModeListProps) {
  const [items, setItems] = useState<ModeListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ModeStateFilter>("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await listFirmModes(firmId, { includeRetired: true });
        if (!alive) return;
        setItems(data);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return () => {
      alive = false;
    };
  }, [firmId, refreshKey]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items
      .filter((it) => {
        const label = modeStateLabel(it);
        if (filter === "built_in") return label === "Built-in";
        if (filter === "customised") return label === "Built-in customised";
        if (filter === "custom") return label === "Custom";
        if (filter === "retired") return label === "Retired";
        return true;
      })
      .filter((it) => {
        if (!q) return true;
        const display = (it.firm_override?.config.display_name as string | undefined) || it.name;
        return it.name.toLowerCase().includes(q) || display.toLowerCase().includes(q);
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [items, filter, search]);

  return (
    <div data-testid="mode-list">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="State filter" className="flex gap-1">
          {STATE_FILTERS.map((f) => (
            <button
              key={f.value}
              role="tab"
              aria-selected={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`rounded-sm border px-2 py-0.5 text-[11px] ${
                filter === f.value
                  ? "border-argus-primary bg-argus-primary text-argus-inverse"
                  : "border-argus-border-subtle bg-surface text-argus-secondary hover:bg-elevated"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          type="search"
          aria-label="Search modes"
          placeholder="Search by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="ml-auto h-7 w-56 rounded-sm border border-argus-border-subtle bg-surface px-2 text-[12px] text-argus-primary"
        />
        {isAdmin ? (
          <button
            type="button"
            onClick={onCreateFresh}
            className="rounded-sm border border-argus-accent-border bg-argus-accent-bg px-2 py-1 text-[11px] font-medium text-argus-accent hover:bg-argus-accent"
          >
            + Create custom mode
          </button>
        ) : null}
      </div>

      {error ? (
        <p className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
          {error}
        </p>
      ) : filtered.length === 0 ? (
        <p className="rounded-argus-md border border-dashed border-argus-border-moderate p-4 text-center text-[12px] text-argus-tertiary">
          No firm-specific modes yet. Click a built-in mode to customise it,
          or create a fresh mode.
        </p>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((item) => (
            <ModeCard key={item.name} item={item} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ModeCard({ item, onSelect }: { item: ModeListItem; onSelect: (i: ModeListItem) => void }) {
  const state = modeStateLabel(item);
  const cfg = item.firm_override?.config;
  const display =
    (cfg?.display_name as string | undefined) ||
    (item.is_builtin ? item.name.replace(/_/g, " ") : item.name);
  const description = (cfg?.description as string | undefined) || "";
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(item)}
        className="w-full rounded-argus-sm border border-argus-border-subtle bg-surface p-3 text-left transition-colors hover:border-argus-border-moderate hover:bg-elevated"
        data-testid={`mode-card-${item.name}`}
      >
        <div className="mb-1 flex items-start justify-between gap-2">
          <span className="font-mono text-[11px] uppercase tracking-wide text-argus-tertiary">
            {item.name}
          </span>
          <span
            className={`shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
              STATE_BADGE_CLASS[state] || ""
            }`}
            data-testid="mode-state-badge"
          >
            {state}
          </span>
        </div>
        <span className="block font-serif text-[14px] font-semibold leading-snug text-argus-primary">
          {display}
        </span>
        {description ? (
          <span className="mt-1 block text-[12px] leading-snug text-argus-tertiary line-clamp-2">
            {description}
          </span>
        ) : null}
      </button>
    </li>
  );
}
