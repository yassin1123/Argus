"use client";

import { useEffect, useMemo, useState } from "react";

import SourceDetailDrawer from "@/components/library/SourceDetailDrawer";
import { listLibrarySources } from "@/lib/api";
import type { SourceItem, TrustLevel } from "@/lib/types";

const TRUST_TONE: Record<TrustLevel, string> = {
  firm_vetted: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  credible_external: "border-argus-credible-border bg-argus-credible-bg text-argus-credible",
  web_general: "border-argus-web-border bg-argus-web-bg text-argus-web",
  contested: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

const TRUST_LABEL: Record<TrustLevel, string> = {
  firm_vetted: "Firm-vetted",
  credible_external: "Credible",
  web_general: "Web",
  contested: "Contested",
};

const TRUST_DOT: Record<TrustLevel, string> = {
  firm_vetted: "bg-argus-firm",
  credible_external: "bg-argus-credible",
  web_general: "bg-argus-web",
  contested: "bg-argus-contested",
};

function fmtSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso.slice(0, 10);
  }
}

function FileGlyph({ kind, className = "" }: { kind: string; className?: string }) {
  if (kind === "url" || kind === "web")
    return (
      <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </svg>
    );
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6M9 13h6M9 17h4" />
    </svg>
  );
}

function FilterChip({
  active,
  onClick,
  children,
  count,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-sm border px-2 py-1 text-[11px] transition-colors ${
        active
          ? "border-argus-primary bg-argus-primary text-argus-inverse"
          : "border-argus-border-subtle bg-surface text-argus-secondary hover:border-argus-border-moderate hover:text-argus-primary"
      }`}
    >
      <span>{children}</span>
      {count !== undefined ? (
        <span className={`font-mono tabular-nums text-[10px] ${active ? "opacity-80" : "text-argus-tertiary"}`}>
          {count}
        </span>
      ) : null}
    </button>
  );
}

export default function LibraryPage() {
  const [items, setItems] = useState<SourceItem[] | null>(null);
  const [trustFilter, setTrustFilter] = useState<"all" | TrustLevel>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [openSource, setOpenSource] = useState<SourceItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const data = await listLibrarySources();
      setItems(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load library");
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const trustCounts = useMemo(() => {
    const c: Record<TrustLevel, number> = {
      firm_vetted: 0,
      credible_external: 0,
      web_general: 0,
      contested: 0,
    };
    for (const s of items ?? []) c[s.trust_level] = (c[s.trust_level] ?? 0) + 1;
    return c;
  }, [items]);

  const fileTypes = useMemo(() => {
    const set = new Set<string>();
    for (const s of items ?? []) if (s.file_type) set.add(s.file_type);
    return Array.from(set).sort();
  }, [items]);

  const visible = useMemo(() => {
    if (!items) return [];
    const q = query.trim().toLowerCase();
    return items.filter((s) => {
      if (trustFilter !== "all" && s.trust_level !== trustFilter) return false;
      if (typeFilter !== "all" && s.file_type !== typeFilter) return false;
      if (!q) return true;
      return (
        s.filename.toLowerCase().includes(q) ||
        (s.notes || "").toLowerCase().includes(q) ||
        (s.source_url || "").toLowerCase().includes(q)
      );
    });
  }, [items, trustFilter, typeFilter, query]);

  return (
    <main className="mx-auto max-w-[1100px] px-8 py-8">
      <header className="mb-6">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">Source Library</h1>
        <p className="mt-1 text-[13px] text-argus-tertiary">
          Firm-wide knowledge — sources promoted to <em className="font-serif">firm</em> scope from any engagement appear here, visible across the firm.
        </p>
      </header>

      {/* Toolbar */}
      <div className="mb-4 space-y-2">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search filenames, URLs, notes…"
              className="w-full rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 pr-8 text-[13px] placeholder:text-argus-quaternary focus:border-argus-border-strong focus:outline-none"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-argus-tertiary hover:text-argus-primary"
              >
                ×
              </button>
            ) : null}
          </div>
          <span className="font-mono text-[11px] tabular-nums text-argus-tertiary">
            {items === null ? "—" : `${visible.length} / ${items.length}`}
          </span>
        </div>

        {/* Trust filter chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="argus-label mr-1">Trust</span>
          <FilterChip active={trustFilter === "all"} onClick={() => setTrustFilter("all")} count={items?.length}>
            All
          </FilterChip>
          {(Object.keys(TRUST_LABEL) as TrustLevel[]).map((t) => (
            <FilterChip
              key={t}
              active={trustFilter === t}
              onClick={() => setTrustFilter(t)}
              count={trustCounts[t]}
            >
              <span className="flex items-center gap-1.5">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${TRUST_DOT[t]}`} aria-hidden />
                {TRUST_LABEL[t]}
              </span>
            </FilterChip>
          ))}
        </div>

        {/* File type filter chips */}
        {fileTypes.length > 1 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="argus-label mr-1">Type</span>
            <FilterChip active={typeFilter === "all"} onClick={() => setTypeFilter("all")}>
              All
            </FilterChip>
            {fileTypes.map((t) => (
              <FilterChip key={t} active={typeFilter === t} onClick={() => setTypeFilter(t)}>
                <span className="font-mono uppercase">{t}</span>
              </FilterChip>
            ))}
          </div>
        ) : null}
      </div>

      {error ? (
        <p className="mb-3 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
          {error}
        </p>
      ) : null}

      {!items ? (
        <p className="text-[13px] text-argus-tertiary">Loading library…</p>
      ) : items.length === 0 ? (
        <div className="rounded-argus-md border border-dashed border-argus-border-moderate p-10 text-center">
          <p className="font-serif text-[16px] text-argus-primary">No firm-wide sources yet.</p>
          <p className="mt-1 text-[12px] text-argus-tertiary">
            Promote a source to <span className="font-mono">firm</span> scope from inside any engagement to share it across the firm.
          </p>
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-argus-md border border-dashed border-argus-border-moderate p-10 text-center">
          <p className="font-serif text-[15px] text-argus-primary">No sources match these filters.</p>
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setTrustFilter("all");
              setTypeFilter("all");
            }}
            className="mt-2 text-[12px] text-argus-accent hover:underline"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div className="overflow-hidden border border-argus-border-subtle bg-surface">
          <table className="w-full table-auto text-[12px]">
            <thead>
              <tr className="border-b border-argus-border-subtle bg-[var(--bg-rail)] text-left text-[10px] uppercase tracking-wider text-argus-tertiary">
                <th className="px-3 py-2 font-semibold">Source</th>
                <th className="px-3 py-2 font-semibold">Type</th>
                <th className="px-3 py-2 font-semibold">Trust</th>
                <th className="px-3 py-2 font-semibold tabular-nums">Chunks</th>
                <th className="px-3 py-2 font-semibold tabular-nums">Size</th>
                <th className="px-3 py-2 font-semibold">Added</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => setOpenSource(s)}
                  className="cursor-pointer border-b border-argus-border-subtle/60 last:border-b-0 hover:bg-elevated"
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <FileGlyph kind={s.file_type} className="shrink-0 text-argus-tertiary" />
                      <span className="font-medium text-argus-primary">{s.filename}</span>
                    </div>
                    {s.notes ? (
                      <div className="ml-6 mt-0.5 line-clamp-1 text-[11px] text-argus-tertiary">{s.notes}</div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 font-mono uppercase text-argus-secondary">{s.file_type}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${TRUST_TONE[s.trust_level]}`}>
                      {TRUST_LABEL[s.trust_level]}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono tabular-nums text-argus-secondary">{s.chunk_count}</td>
                  <td className="px-3 py-2 font-mono tabular-nums text-argus-tertiary">{fmtSize(s.original_size)}</td>
                  <td className="px-3 py-2 text-argus-tertiary">{fmtDate(s.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <SourceDetailDrawer
        source={openSource}
        onClose={() => setOpenSource(null)}
        onUpdated={(next) => {
          setItems((prev) => prev?.map((s) => (s.id === next.id ? next : s)) ?? prev);
          setOpenSource(next);
        }}
        onDeleted={(id) => {
          setItems((prev) => prev?.filter((s) => s.id !== id) ?? prev);
        }}
        canPromoteFirm
      />
    </main>
  );
}
