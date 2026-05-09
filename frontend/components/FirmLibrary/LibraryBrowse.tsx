"use client";

import { useEffect, useMemo, useState } from "react";

import {
  type FirmContent,
  type FirmContentCategory,
  listFirmContent,
} from "@/lib/api/firmLibrary";

const CATEGORY_LABEL: Record<FirmContentCategory, string> = {
  playbook: "Playbook",
  sector_primer: "Sector primer",
  prior_report: "Prior report",
  framework: "Framework",
  methodology: "Methodology",
  other: "Other",
};

type StatusFilter = "active" | "retired" | "all";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso.slice(0, 10);
  }
}

export interface LibraryBrowseProps {
  firmId: string;
  /** Bumping this prop forces a refetch from the parent (e.g. after upload). */
  refreshKey?: number;
  onSelect?: (content: FirmContent) => void;
}

export default function LibraryBrowse({
  firmId,
  refreshKey = 0,
  onSelect,
}: LibraryBrowseProps) {
  const [items, setItems] = useState<FirmContent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<FirmContentCategory | "">("");
  const [sector, setSector] = useState<string>("");
  const [mode, setMode] = useState<string>("");
  const [status, setStatus] = useState<StatusFilter>("active");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const rows = await listFirmContent(firmId, {
          // The backend's filter takes one value at a time; the front-end
          // sends category/sector/mode literally. include_retired only
          // when the user picks "all" or "retired" — for retired-only we
          // include and post-filter (the API doesn't have an "only
          // retired" mode today; small enough to filter client-side).
          category: category || undefined,
          sector: sector || undefined,
          mode: mode || undefined,
          includeRetired: status !== "active",
        });
        if (!alive) return;
        const next = status === "retired" ? rows.filter((r) => r.retired_at) : rows;
        setItems(next);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return () => {
      alive = false;
    };
  }, [firmId, refreshKey, category, sector, mode, status]);

  const allSectors = useMemo(() => {
    const set = new Set<string>();
    for (const it of items ?? []) for (const t of it.sector_tags) set.add(t);
    return Array.from(set).sort();
  }, [items]);

  const allModes = useMemo(() => {
    const set = new Set<string>();
    for (const it of items ?? []) for (const m of it.intended_modes) set.add(m);
    return Array.from(set).sort();
  }, [items]);

  const clearFilters = () => {
    setCategory("");
    setSector("");
    setMode("");
    setStatus("active");
  };

  const anyFilterActive = category !== "" || sector !== "" || mode !== "" || status !== "active";

  return (
    <section data-testid="firm-library-browse">
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div>
          <label className="argus-label mb-1 block">Category</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as FirmContentCategory | "")}
            className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[12px] focus:border-argus-border-strong focus:outline-none"
            aria-label="Filter by category"
          >
            <option value="">All categories</option>
            {(Object.keys(CATEGORY_LABEL) as FirmContentCategory[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABEL[c]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="argus-label mb-1 block">Sector</label>
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[12px] focus:border-argus-border-strong focus:outline-none"
            aria-label="Filter by sector"
          >
            <option value="">All sectors</option>
            {allSectors.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="argus-label mb-1 block">Mode</label>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[12px] focus:border-argus-border-strong focus:outline-none"
            aria-label="Filter by mode"
          >
            <option value="">All modes</option>
            {allModes.map((m) => (
              <option key={m} value={m}>
                {m.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="argus-label mb-1 block">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as StatusFilter)}
            className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[12px] focus:border-argus-border-strong focus:outline-none"
            aria-label="Filter by status"
          >
            <option value="active">Active</option>
            <option value="retired">Retired</option>
            <option value="all">All</option>
          </select>
        </div>
        {anyFilterActive ? (
          <button
            type="button"
            onClick={clearFilters}
            className="ml-auto self-end text-[11px] text-argus-tertiary hover:text-argus-primary"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      {error ? (
        <p
          role="alert"
          className="mb-3 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested"
        >
          {error}
        </p>
      ) : null}

      {items === null ? (
        <p className="text-[13px] text-argus-tertiary">Loading library…</p>
      ) : items.length === 0 ? (
        <div
          className="rounded-argus-md border border-dashed border-argus-border-moderate p-8 text-center"
          data-testid="firm-library-empty"
        >
          <p className="font-serif text-[15px] text-argus-primary">
            {anyFilterActive ? "No items match these filters." : "No content yet."}
          </p>
          <p className="mt-1 text-[12px] text-argus-tertiary">
            {anyFilterActive
              ? "Adjust the filters above or clear them."
              : "Upload your first playbook above to populate the firm library."}
          </p>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {items.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onSelect?.(c)}
                aria-label={`Open ${c.title}`}
                className="flex w-full flex-col rounded-argus-md border border-argus-border-subtle bg-surface px-3 py-2 text-left transition-colors hover:border-argus-border-moderate hover:bg-elevated"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-argus-primary line-clamp-2">
                    {c.title}
                  </span>
                  {c.retired_at ? (
                    <span
                      className="ml-1 shrink-0 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-argus-contested"
                      data-testid="retired-badge"
                    >
                      Retired
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-argus-tertiary">
                  <span className="rounded-sm border border-argus-border-subtle bg-elevated px-1.5 py-0.5">
                    {CATEGORY_LABEL[c.category] ?? c.category}
                  </span>
                  {c.sector_tags.slice(0, 3).map((s) => (
                    <span
                      key={s}
                      className="rounded-sm bg-elevated px-1 py-0.5 text-argus-secondary"
                    >
                      {s}
                    </span>
                  ))}
                  {c.intended_modes.slice(0, 2).map((m) => (
                    <span
                      key={m}
                      className="rounded-sm bg-elevated px-1 py-0.5 font-mono text-[10px] text-argus-secondary"
                    >
                      {m}
                    </span>
                  ))}
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-argus-tertiary">
                  <span className="font-mono tabular-nums">
                    {c.chunk_count} chunks
                  </span>
                  <span>Added {fmtDate(c.uploaded_at)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
