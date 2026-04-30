"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { listEngagementSources, searchChunks } from "@/lib/api";
import { useSelection } from "@/lib/SelectionContext";
import type {
  ChunkSearchResult,
  EvidenceObjectRow,
  SessionDetail,
  SourceItem,
  TrustLevel,
} from "@/lib/types";
import AddSourcePanel from "./AddSourcePanel";
import { inferTrustTier, type TrustTier } from "./citation";

type Tab = "engagement" | "library" | "external";

const TIER_DOT: Record<TrustTier, string> = {
  firm: "bg-argus-firm",
  credible: "bg-argus-credible",
  web: "bg-argus-web",
  contested: "bg-argus-contested",
};

const TIER_LABEL: Record<TrustTier, string> = {
  firm: "Firm",
  credible: "Credible",
  web: "Web",
  contested: "Contested",
};

function FileIcon({ kind, className = "" }: { kind: string; className?: string }) {
  // Different glyphs by source type — simple, monoline.
  if (kind === "document" || kind === "knowledge")
    return (
      <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
        <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
        <path d="M14 3v6h6M9 13h6M9 17h4" />
      </svg>
    );
  if (kind === "call")
    return (
      <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
        <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19 19 0 0 1-8.3-3 19 19 0 0 1-6-6 19 19 0 0 1-3-8.3A2 2 0 0 1 4.1 2.5h3a2 2 0 0 1 2 1.7 13 13 0 0 0 .7 2.8 2 2 0 0 1-.5 2.1L8 10.3a16 16 0 0 0 6 6l1.2-1.3a2 2 0 0 1 2.1-.5 13 13 0 0 0 2.8.7 2 2 0 0 1 1.7 2z" />
      </svg>
    );
  return (
    // web (default)
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

function SourceRow({ ev, selected, onClick }: { ev: EvidenceObjectRow; selected: boolean; onClick: () => void }) {
  const tier = inferTrustTier(ev);
  const date = ev.source_date ? ev.source_date.slice(0, 10) : "";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex w-full items-start gap-2 px-3 py-2 text-left text-[12px] transition-colors ${
        selected ? "bg-elevated" : "hover:bg-elevated"
      }`}
    >
      <FileIcon kind={ev.source_type || "web"} className="mt-0.5 shrink-0 text-argus-tertiary group-hover:text-argus-primary" />
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 font-medium text-argus-primary">
          {ev.source_title || "Untitled"}
        </span>
        <span className="mt-0.5 flex items-center gap-2 text-[10px] text-argus-tertiary">
          <span className="flex items-center gap-1">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${TIER_DOT[tier]}`} aria-hidden />
            {TIER_LABEL[tier]}
          </span>
          {date ? <span className="font-mono tabular-nums">{date}</span> : null}
        </span>
      </span>
    </button>
  );
}

export default function SourceRail({ session }: { session: SessionDetail }) {
  const [tab, setTab] = useState<Tab>("engagement");
  const [query, setQuery] = useState("");
  const [filterScope, setFilterScope] = useState<"all" | "selected" | "noweb" | "recent">("all");
  const [addOpen, setAddOpen] = useState(false);
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [sourcesError, setSourcesError] = useState<string | null>(null);

  const refreshSources = useCallback(async () => {
    try {
      const data = await listEngagementSources(session.id);
      setSources(data);
      setSourcesError(null);
    } catch (e) {
      setSourcesError(e instanceof Error ? e.message : "Failed to load sources");
    }
  }, [session.id]);

  useEffect(() => {
    void refreshSources();
  }, [refreshSources]);

  const hasProcessing = useMemo(
    () => sources.some((s) => s.chunk_count === 0),
    [sources],
  );

  // Poll while a source is still being processed (chunk_count === 0)
  useEffect(() => {
    if (!hasProcessing) return;
    const id = setInterval(() => void refreshSources(), 4000);
    return () => clearInterval(id);
  }, [hasProcessing, refreshSources]);

  const { selectedClaimId } = useSelection();
  const evidence = useMemo(
    () => session.evidence_objects ?? [],
    [session.evidence_objects],
  );
  const claimSupport = useMemo(
    () => session.report?.claim_support ?? [],
    [session.report?.claim_support],
  );

  // Filter by selected claim if any
  const claimEvidenceIds = useMemo(() => {
    if (!selectedClaimId) return null;
    const row = claimSupport.find((r) => r.claim_id === selectedClaimId);
    return row?.evidence_object_ids ? new Set(row.evidence_object_ids) : null;
  }, [selectedClaimId, claimSupport]);

  // Filtered + searched
  const visible = useMemo(() => {
    let list = [...evidence];
    if (tab === "external") list = list.filter((e) => e.source_type === "web");
    if (tab === "library") list = list.filter((e) => e.source_type === "document" || e.source_type === "knowledge");
    if (claimEvidenceIds) list = list.filter((e) => claimEvidenceIds.has(e.id));
    if (filterScope === "noweb") list = list.filter((e) => e.source_type !== "web");
    if (filterScope === "recent") {
      const cutoff = new Date();
      cutoff.setMonth(cutoff.getMonth() - 12);
      list = list.filter((e) => {
        const d = e.source_date ? new Date(e.source_date) : null;
        return d ? d >= cutoff : true;
      });
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(
        (e) =>
          (e.source_title || "").toLowerCase().includes(q) ||
          (e.quote || "").toLowerCase().includes(q),
      );
    }
    // Sort: firm > credible > web > contested, then by score desc
    return list.sort((a, b) => {
      const ta = inferTrustTier(a);
      const tb = inferTrustTier(b);
      const order: TrustTier[] = ["firm", "credible", "web", "contested"];
      const ai = order.indexOf(ta);
      const bi = order.indexOf(tb);
      if (ai !== bi) return ai - bi;
      return (b.source_score ?? 0) - (a.source_score ?? 0);
    });
  }, [evidence, tab, claimEvidenceIds, filterScope, query]);

  // Group by tier for display
  const grouped = useMemo(() => {
    const groups: Record<TrustTier, EvidenceObjectRow[]> = { firm: [], credible: [], web: [], contested: [] };
    for (const e of visible) groups[inferTrustTier(e)].push(e);
    return groups;
  }, [visible]);

  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <aside className="argus-pane-source flex flex-col">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-argus-border-subtle bg-[var(--bg-rail)] px-3 pt-3 pb-2">
        <div className="argus-label mb-2 flex items-center justify-between">
          <span>Sources</span>
          <span className="font-mono tabular-nums normal-case tracking-normal text-argus-tertiary">
            {evidence.length}
          </span>
        </div>

        {/* Tabs */}
        <div className="mb-2 flex border-b border-argus-border-subtle text-[11px]">
          {([
            ["engagement", "This"],
            ["library", "Library"],
            ["external", "External"],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className={`-mb-px border-b-2 px-2 py-1.5 transition-colors ${
                tab === k
                  ? "border-argus-primary font-semibold text-argus-primary"
                  : "border-transparent text-argus-tertiary hover:text-argus-secondary"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Search */}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search sources…"
          className="w-full rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[12px] placeholder:text-argus-quaternary focus:border-argus-border-strong focus:outline-none"
        />

        {/* Filter chips */}
        <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
          {([
            ["all", "All"],
            ["noweb", "Exclude web"],
            ["recent", "Last 12mo"],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setFilterScope(k)}
              className={`rounded-sm border px-1.5 py-0.5 transition-colors ${
                filterScope === k
                  ? "border-argus-primary bg-argus-primary text-argus-inverse"
                  : "border-argus-border-subtle bg-surface text-argus-tertiary hover:text-argus-primary"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {claimEvidenceIds ? (
          <div className="mt-2 rounded-sm border border-argus-credible-border bg-argus-credible-bg px-2 py-1 text-[10px] text-argus-credible">
            Filtered by claim {selectedClaimId}
          </div>
        ) : null}

        {sourcesError ? (
          <p className="mt-2 text-[10px] text-argus-contested">{sourcesError}</p>
        ) : null}
      </div>

      <ProcessingStrip sources={sources} />


      {/* List — show chunk search results when query is non-empty, else source list */}
      <div className="flex-1">
        {query.trim() ? (
          <ChunkSearchPanel sessionId={session.id} query={query} />
        ) : visible.length === 0 ? (
          <p className="p-4 text-[12px] text-argus-tertiary">No sources match.</p>
        ) : (
          (Object.entries(grouped) as [TrustTier, EvidenceObjectRow[]][])
            .filter(([, list]) => list.length > 0)
            .map(([tier, list]) => (
              <section key={tier} className="border-b border-argus-border-subtle/60 last:border-b-0">
                <div className="bg-elevated/60 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-argus-tertiary">
                  {TIER_LABEL[tier]} <span className="font-mono tabular-nums">· {list.length}</span>
                </div>
                <ul>
                  {list.map((ev) => (
                    <li key={ev.id}>
                      <SourceRow
                        ev={ev}
                        selected={selectedId === ev.id}
                        onClick={() => setSelectedId(selectedId === ev.id ? null : ev.id)}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ))
        )}
      </div>

      {/* Add source */}
      <div className="sticky bottom-0 border-t border-argus-border-subtle bg-[var(--bg-rail)] p-2">
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="w-full rounded-sm border border-dashed border-argus-border-moderate px-2 py-1.5 text-[11px] text-argus-tertiary hover:border-argus-primary hover:text-argus-primary"
        >
          + Add source · upload, URL
        </button>
      </div>
      <AddSourcePanel
        engagementId={session.id}
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onAdded={() => void refreshSources()}
      />
    </aside>
  );
}

// ----------------------------------------------------------------------------
// ProcessingStrip — surfaces uploaded sources still being chunked/embedded
// (chunk_count === 0). Disappears once all sources have at least one chunk.
// ----------------------------------------------------------------------------

function ProcessingStrip({ sources }: { sources: SourceItem[] }) {
  const processing = sources.filter((s) => s.chunk_count === 0);
  const justReady = useMemo(
    () =>
      sources
        .filter((s) => {
          if (s.chunk_count <= 0) return false;
          if (!s.created_at) return false;
          return Date.now() - new Date(s.created_at).getTime() < 60_000;
        })
        .slice(0, 3),
    [sources],
  );

  if (processing.length === 0 && justReady.length === 0) return null;
  return (
    <section
      aria-label="Processing sources"
      className="border-b border-argus-border-subtle bg-[var(--bg-rail)] px-3 py-2"
    >
      <div className="argus-label mb-1 flex items-center justify-between">
        <span>Recently added</span>
        <span className="font-mono tabular-nums normal-case tracking-normal text-argus-tertiary">
          {processing.length} processing
        </span>
      </div>
      <ul className="space-y-1">
        {processing.map((s) => (
          <li key={s.id} className="flex items-center gap-2 text-[11px]">
            <span aria-hidden className="argus-cite-spinner shrink-0" style={{ color: "var(--trust-web)" }} />
            <span className="min-w-0 flex-1 truncate text-argus-secondary">{s.filename}</span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-argus-web">
              {processingPhase(s)}
            </span>
          </li>
        ))}
        {justReady.map((s) => (
          <li key={s.id} className="flex items-center gap-2 text-[11px]">
            <span aria-hidden className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-argus-firm" />
            <span className="min-w-0 flex-1 truncate text-argus-secondary">{s.filename}</span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-argus-firm">
              ready · {s.chunk_count}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Surface a coarse phase label for a still-processing source. We don't have
 * a real per-step status field — so we approximate from age and shape.
 */
function processingPhase(s: SourceItem): string {
  if (!s.created_at) return "processing";
  const ageMs = Date.now() - new Date(s.created_at).getTime();
  if (ageMs < 4_000) return "uploading";
  if (ageMs < 12_000) return "extracting";
  if (ageMs < 30_000) return "chunking";
  return "embedding";
}

// ----------------------------------------------------------------------------
// ChunkSearchPanel — debounced hybrid search hitting /api/sources/search
// ----------------------------------------------------------------------------

const TRUST_TIER_FROM_LEVEL: Record<TrustLevel, TrustTier> = {
  firm_vetted: "firm",
  credible_external: "credible",
  web_general: "web",
  contested: "contested",
};

function highlightSnippet(snippet: string | null, content: string): React.ReactNode {
  if (snippet) {
    // Snippet contains <<term>> markers from ts_headline
    const parts = snippet.split(/(<<[^>]+>>)/g);
    return parts.map((p, i) => {
      const m = p.match(/^<<(.+)>>$/);
      if (m) return <mark key={i} className="rounded-sm bg-argus-web-bg px-0.5 text-argus-web">{m[1]}</mark>;
      return <span key={i}>{p}</span>;
    });
  }
  return content.slice(0, 200) + (content.length > 200 ? "…" : "");
}

function ChunkSearchPanel({ sessionId, query }: { sessionId: string; query: string }) {
  const [results, setResults] = useState<ChunkSearchResult[] | null>(null);
  const [meta, setMeta] = useState<{ vector: number; keyword: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    const handle = setTimeout(async () => {
      try {
        const data = await searchChunks(sessionId, trimmed, { mode: "hybrid", k: 20 });
        if (cancelled) return;
        setResults(data.results);
        setMeta({ vector: data.vector_count, keyword: data.keyword_count });
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Search failed");
        setResults([]);
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [sessionId, query]);

  if (busy && results === null) {
    return <p className="p-4 text-[11px] text-argus-tertiary">Searching…</p>;
  }
  if (error) {
    return <p className="p-4 text-[11px] text-argus-contested">{error}</p>;
  }
  if (!results || results.length === 0) {
    return (
      <div className="p-4 text-[11px] text-argus-tertiary">
        No matches.
        {meta ? (
          <span className="block mt-1 font-mono tabular-nums text-argus-quaternary">
            vector: {meta.vector} · keyword: {meta.keyword}
          </span>
        ) : null}
      </div>
    );
  }
  return (
    <div>
      <div className="bg-elevated/60 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-argus-tertiary">
        Hybrid · {results.length} of <span className="font-mono tabular-nums">{(meta?.vector ?? 0) + (meta?.keyword ?? 0)}</span>
      </div>
      <ul className="divide-y divide-argus-border-subtle/60">
        {results.map((r) => {
          const tier = TRUST_TIER_FROM_LEVEL[r.trust_level] ?? "web";
          return (
            <li key={r.id} className="px-3 py-2 text-[12px]">
              <div className="flex items-center gap-2 text-[10px] text-argus-tertiary">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${TIER_DOT[tier]}`} aria-hidden />
                <span>{TIER_LABEL[tier]}</span>
                <span>·</span>
                <span className="line-clamp-1 font-medium text-argus-secondary">{r.source_filename || "Untitled"}</span>
                {r.page ? (
                  <span className="font-mono tabular-nums">p.{r.page}</span>
                ) : r.slide ? (
                  <span className="font-mono tabular-nums">slide {r.slide}</span>
                ) : r.timestamp_str ? (
                  <span className="font-mono tabular-nums">{r.timestamp_str}</span>
                ) : null}
              </div>
              {r.section_heading ? (
                <div className="mt-0.5 text-[10px] font-semibold text-argus-primary">{r.section_heading}</div>
              ) : null}
              <div className="mt-1 line-clamp-3 text-[11px] leading-snug text-argus-secondary">
                {highlightSnippet(r.snippet ?? null, r.content)}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

