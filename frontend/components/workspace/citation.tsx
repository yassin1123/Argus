"use client";

import { useEffect, useRef, useState } from "react";

import type { EvidenceObjectRow, NliLabel, NliResult } from "@/lib/types";

export type TrustTier = "firm" | "credible" | "web" | "contested";

export type NliState = "verifying" | "supported" | "weak" | "unsupported" | "unknown";

export function inferTrustTier(ev?: EvidenceObjectRow | null): TrustTier {
  if (!ev) return "web";
  if (ev.is_inference) return "contested";
  const type = (ev.source_type || "").toLowerCase();
  const conf = (ev.confidence || "").toLowerCase();
  // Phase 2 / Week 5 / Day 4: firm_library is firm-trust by definition
  // (statutorily curated by the firm's admins). Everything else keeps
  // its existing tier-resolution.
  if (type === "firm_library" || type === "document" || type === "knowledge") return "firm";
  if (conf === "high") return "credible";
  if (conf === "low") return "contested";
  return "web";
}


/**
 * Render-side breadcrumb for a firm-library evidence row.
 * Returns null when the evidence isn't from the firm library, so callers
 * can use it as a conditional renderer:
 *
 *   {renderFirmLibraryBreadcrumb(ev) ?? null}
 */
export function firmLibraryBreadcrumb(
  ev: EvidenceObjectRow,
): { title: string; category: string; section: string } | null {
  if ((ev.source_type || "").toLowerCase() !== "firm_library") return null;
  const meta = (ev.metadata || {}) as Record<string, unknown>;
  return {
    title: String(meta.firm_library_title ?? ev.source_title ?? ""),
    category: String(meta.category ?? ""),
    section: String(meta.section ?? ""),
  };
}

const TIER_LABEL: Record<TrustTier, string> = {
  firm: "Firm-vetted",
  credible: "Credible external",
  web: "Web-general",
  contested: "Contested / single-source",
};

const NLI_LABEL: Record<NliState, string> = {
  verifying: "Verifying…",
  supported: "Supported",
  weak: "Weak — partial support",
  unsupported: "Unsupported — chunk contradicts the claim",
  unknown: "Not verified",
};

/** Aggregate the NLI results for THIS chunk into a single visual state. */
export function nliStateFor(
  chunkId: string | null,
  results: NliResult[] | undefined,
  verifying: boolean,
): NliState {
  if (!results || results.length === 0) return verifying ? "verifying" : "unknown";
  if (chunkId) {
    const r = results.find((x) => x.chunk_id === chunkId);
    if (!r) return verifying ? "verifying" : "unknown";
    if (r.label === "contradiction") return "unsupported";
    if (r.label === "neutral") return "weak";
    if (r.label === "entailment") return "supported";
    return "unknown";
  }
  // No chunk_id: aggregate worst case.
  const labels = results.map((r) => r.label);
  if (labels.includes("contradiction" as NliLabel)) return "unsupported";
  if (labels.includes("entailment" as NliLabel)) return "supported";
  if (labels.includes("neutral" as NliLabel)) return "weak";
  return verifying ? "verifying" : "unknown";
}

/** Format chunk-level location: "Page 14" / "Slide 7" / "00:12:34 — Sarah Chen" / "Section: …" */
export function formatChunkLocation(ev: EvidenceObjectRow): string | null {
  const anyEv = ev as unknown as Record<string, unknown>;
  const page = anyEv.page as number | undefined;
  const slide = anyEv.slide as number | undefined;
  const ts = anyEv.timestamp_str as string | undefined;
  const speaker = anyEv.speaker as string | undefined;
  const section = anyEv.section_heading as string | undefined;
  const sourceType = (ev.source_type || "").toLowerCase();

  if (page) return `Page ${page}` + (sourceType === "pdf" ? " (PDF)" : "");
  if (slide) return `Slide ${slide}`;
  if (ts) return speaker ? `${ts} — ${speaker}` : ts;
  if (section) return `Section: "${section}"`;
  return null;
}

/**
 * CitationMarker — inline `[N]` with hover popover + NLI verification state.
 * Trust color is the fill; an additional border ring or dashed border layers
 * NLI verdict on top (red ring = contradiction, dashed = weak, pulse = verifying).
 */
export function CitationMarker({
  n,
  ev,
  nliResults,
  verifying = false,
  onSelect,
}: {
  n: number;
  ev?: EvidenceObjectRow | null;
  nliResults?: NliResult[];
  verifying?: boolean;
  onSelect?: (ev: EvidenceObjectRow) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement | null>(null);
  const tier = inferTrustTier(ev);
  const nli = nliStateFor(ev?.id || null, nliResults, verifying);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const failureIcon =
    nli === "unsupported" || nli === "weak" ? (
      <span aria-hidden className="ml-0.5 text-[9px] leading-none">⚠</span>
    ) : null;

  return (
    <span ref={ref} className="relative inline-block">
      <button
        type="button"
        className="argus-cite"
        data-trust={tier}
        data-nli={nli}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => {
          setTimeout(() => {
            if (ref.current && !ref.current.matches(":hover")) setOpen(false);
          }, 120);
        }}
        onClick={(e) => {
          e.preventDefault();
          if (ev && onSelect) onSelect(ev);
          else setOpen((v) => !v);
        }}
        aria-label={`Citation ${n} — ${TIER_LABEL[tier]} — ${NLI_LABEL[nli]}`}
        title={`[${n}] ${TIER_LABEL[tier]} · ${NLI_LABEL[nli]}`}
      >
        {nli === "verifying" ? <span className="argus-cite-spinner" aria-hidden /> : null}
        {nli !== "verifying" ? n : null}
        {failureIcon}
      </button>
      {open && ev ? (
        <CitationPopover
          ev={ev}
          tier={tier}
          nli={nli}
          nliScore={
            nliResults?.find((r) => r.chunk_id === ev.id)?.score ?? null
          }
          onSelect={onSelect}
        />
      ) : null}
    </span>
  );
}

function CitationPopover({
  ev,
  tier,
  nli,
  nliScore,
  onSelect,
}: {
  ev: EvidenceObjectRow;
  tier: TrustTier;
  nli: NliState;
  nliScore: number | null;
  onSelect?: (ev: EvidenceObjectRow) => void;
}) {
  const location = formatChunkLocation(ev);
  const firmLib = firmLibraryBreadcrumb(ev);

  return (
    <span
      role="dialog"
      data-source-type={ev.source_type || ""}
      className="absolute left-0 top-full z-40 mt-1 block w-[360px] rounded-argus-sm border border-argus-border-moderate bg-surface p-3 shadow-popover"
      onMouseEnter={(e) => e.stopPropagation()}
    >
      {/* Trust + date row */}
      <span className="mb-1 flex items-center justify-between gap-2">
        <span
          className="argus-confidence"
          data-level={tier === "firm" ? "high" : tier === "contested" ? "contested" : "medium"}
        >
          {firmLib ? "📚 Firm Library" : TIER_LABEL[tier]}
        </span>
        <span className="text-[10px] text-argus-tertiary tabular-nums">
          {ev.source_date ? ev.source_date.slice(0, 10) : ""}
        </span>
      </span>

      {/* Source title — firm-library renders the breadcrumb form
          "📚 Firm Library — {title} ({category})" so the citation
          identity is unambiguous in the popover and in PDF/DOCX
          footnote exports that read this same data. */}
      {firmLib ? (
        <span className="block font-serif text-[13px] font-semibold leading-snug text-argus-primary">
          {firmLib.title || "Untitled firm content"}
          {firmLib.category ? (
            <span className="ml-1 font-mono text-[10px] uppercase tracking-wide text-argus-tertiary">
              ({firmLib.category.replaceAll("_", " ")})
            </span>
          ) : null}
        </span>
      ) : (
        <span className="block font-serif text-[13px] font-semibold leading-snug text-argus-primary">
          {ev.source_title || "Untitled source"}
        </span>
      )}

      {/* Phase 4 location row — page / slide / timestamp / section, in mono.
          Firm-library citations render their section explicitly so the
          breadcrumb ("Firm Library — Playbook · Section: Sourcing") is
          fully reconstructable from the popover. */}
      {firmLib?.section ? (
        <span className="mt-1 block font-mono text-[10px] uppercase tracking-wide text-argus-tertiary">
          Section: {firmLib.section}
        </span>
      ) : location ? (
        <span className="mt-1 block font-mono text-[10px] uppercase tracking-wide text-argus-tertiary">
          {location}
        </span>
      ) : null}

      {/* Quoted passage */}
      {ev.quote ? (
        <span className="mt-2 block border-l-2 border-argus-border-moderate pl-2 font-serif text-[12px] italic leading-snug text-argus-secondary">
          “{ev.quote.length > 240 ? `${ev.quote.slice(0, 240)}…` : ev.quote}”
        </span>
      ) : null}

      {/* Phase 8 — Verification row */}
      <span className="mt-2 flex items-center justify-between gap-2 border-t border-argus-border-subtle pt-2 text-[10px]">
        <span className="argus-label normal-case tracking-normal">Verification</span>
        <span className="flex items-center gap-1.5">
          <NliDot nli={nli} />
          <span className={`font-medium ${nliColorClass(nli)}`}>{NLI_LABEL[nli]}</span>
          {nliScore !== null && nli !== "verifying" && nli !== "unknown" ? (
            <span className="font-mono tabular-nums text-argus-tertiary">
              {nliScore.toFixed(2)}
            </span>
          ) : null}
        </span>
      </span>

      {/* Bottom action row */}
      <span className="mt-2 flex items-center justify-between text-[10px] text-argus-tertiary">
        <span>
          {ev.source_type || "source"} ·{" "}
          <span className="font-mono tabular-nums">conf {ev.confidence ?? "—"}</span>
        </span>
        {ev.source_url ? (
          <a
            href={ev.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-argus-accent hover:underline"
          >
            Open source ↗
          </a>
        ) : onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(ev)}
            className="font-medium text-argus-accent hover:underline"
          >
            Jump to source →
          </button>
        ) : null}
      </span>
    </span>
  );
}

function NliDot({ nli }: { nli: NliState }) {
  const cls =
    nli === "supported"
      ? "bg-argus-firm"
      : nli === "weak"
        ? "bg-argus-web"
        : nli === "unsupported"
          ? "bg-argus-contested"
          : nli === "verifying"
            ? "bg-argus-tertiary animate-pulse"
            : "bg-argus-tertiary";
  return <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${cls}`} />;
}

function nliColorClass(nli: NliState): string {
  if (nli === "supported") return "text-argus-firm";
  if (nli === "weak") return "text-argus-web";
  if (nli === "unsupported") return "text-argus-contested";
  return "text-argus-tertiary";
}

/**
 * ConfidencePill — paragraph-level confidence indicator.
 */
export function ConfidencePill({ level }: { level: "high" | "medium" | "contested" }) {
  return (
    <span className="argus-confidence" data-level={level}>
      {level === "high" ? "High" : level === "medium" ? "Medium" : "Contested"}
    </span>
  );
}
