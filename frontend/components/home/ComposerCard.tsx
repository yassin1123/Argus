"use client";

import { useState } from "react";
import { createSession, submitUrl, uploadFile } from "@/lib/api";
import { useRouter } from "next/navigation";
import { AnimatedExpand } from "@/components/ui/AnimatedExpand";
import { Chip } from "@/components/ui/Chip";
import { AutoGrowTextarea } from "./AutoGrowTextarea";

function PaperclipIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

const REPORT_MODES = [
  { value: "general", label: "General" },
  { value: "market_entry", label: "Market entry" },
  { value: "due_diligence", label: "Due diligence" },
  { value: "growth_strategy", label: "Growth" },
] as const;

const EXAMPLE_PROMPTS = [
  "Should we expand our B2B SaaS into the EU in the next 18 months?",
  "Compare vendor A vs vendor B for enterprise HRIS — decision in 90 days.",
  "What are the top risks if we acquire a regional competitor this quarter?",
] as const;

function titleFromQuery(text: string): string {
  const words = text.trim().split(/\s+/).filter(Boolean).slice(0, 6);
  const t = words.join(" ");
  return t || text.trim().slice(0, 80);
}

function Spinner() {
  return (
    <svg
      className="h-3.5 w-3.5 animate-spin text-white"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

export function ComposerCard() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [url, setUrl] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [reportMode, setReportMode] = useState("general");
  const [panel, setPanel] = useState<"mode" | "sources" | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cardFocused, setCardFocused] = useState(false);

  const modeLabel =
    REPORT_MODES.find((m) => m.value === reportMode)?.label ?? "General";
  const sourceCount = files.length + (url.trim() ? 1 : 0);

  const handleSubmit = async () => {
    if (!query.trim()) return;
    setError(null);
    setLoading(true);
    try {
      const session = await createSession(query, undefined, reportMode);
      const sid = session.session_id;
      for (const file of files) {
        await uploadFile(sid, file);
      }
      if (url.trim()) {
        await submitUrl(sid, url.trim());
      }
      router.push(`/sessions/${sid}/intake`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={`rounded-[20px] border border-argus-border-subtle bg-surface shadow-argus transition-shadow duration-150 ${
        cardFocused ? "shadow-[0_0_0_3px_rgba(45,107,228,0.08)]" : ""
      }`}
    >
      <div className="flex items-center gap-2 border-b border-argus-border-subtle px-5 py-3">
        <Chip
          active={panel === "mode"}
          onClick={() => setPanel(panel === "mode" ? null : "mode")}
        >
          Mode · {modeLabel}
        </Chip>
        <Chip
          active={panel === "sources"}
          onClick={() => setPanel(panel === "sources" ? null : "sources")}
        >
          Sources
          {sourceCount > 0 && (
            <span className="ml-1 text-argus-accent">· {sourceCount}</span>
          )}
        </Chip>
        <span className="ml-auto text-xs text-argus-tertiary">Structured report</span>
      </div>

      <AnimatedExpand show={panel === "mode"}>
        <div className="border-b border-argus-border-subtle bg-elevated/80 px-5 py-4">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Consulting mode
          </p>
          <div className="flex flex-wrap gap-2">
            {REPORT_MODES.map((m) => (
              <Chip
                key={m.value}
                active={reportMode === m.value}
                onClick={() => setReportMode(m.value)}
              >
                {m.label}
              </Chip>
            ))}
          </div>
          <p className="mt-3 text-xs text-argus-tertiary">
            Modes set minimum evidence depth and research branches where configured.
          </p>
        </div>
      </AnimatedExpand>

      <AnimatedExpand show={panel === "sources"}>
        <div className="border-b border-argus-border-subtle bg-elevated/80 px-5 py-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Optional URL
          </p>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            className="mb-4 w-full rounded-argus border border-argus-border-subtle bg-surface px-3 py-2 text-sm text-argus-primary placeholder:text-argus-tertiary focus:border-argus-border-strong focus:outline-none"
          />
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
            Files (PDF, CSV, JSON)
          </p>
          <label className="flex cursor-pointer flex-col items-center justify-center rounded-argus-sm border border-dashed border-argus-border-subtle bg-canvas/50 px-4 py-8 text-center text-sm text-argus-secondary transition-colors duration-150 hover:border-argus-border-moderate hover:bg-overlay/80">
            <input
              type="file"
              multiple
              accept=".pdf,.csv,.json,application/pdf,text/csv,application/json"
              className="sr-only"
              onChange={(e) =>
                setFiles(e.target.files ? Array.from(e.target.files) : [])
              }
            />
            Drop files or click to browse
            {files.length > 0 && (
              <span className="mt-2 text-xs text-argus-accent">
                {files.length} file{files.length !== 1 ? "s" : ""} selected
              </span>
            )}
          </label>
        </div>
      </AnimatedExpand>

      <div className="border-b border-argus-border-subtle px-5 py-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
          Try an example
        </p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuery(ex);
                setCardFocused(true);
              }}
              className="max-w-full rounded-full border border-argus-border-subtle bg-canvas px-3 py-1.5 text-left text-xs text-argus-secondary transition-colors hover:border-argus-border-moderate hover:text-argus-primary"
            >
              <span className="line-clamp-2">{ex}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-argus-tertiary">
          Optional: attach a URL or PDF/CSV/JSON under Sources for stronger grounding.
        </p>
      </div>

      <div className="px-5 pt-4">
        <label className="sr-only" htmlFor="composer">
          Your question
        </label>
        <AutoGrowTextarea
          id="composer"
          value={query}
          onChange={setQuery}
          onFocus={() => setCardFocused(true)}
          onBlur={() => setCardFocused(false)}
        />
      </div>

      {error && (
        <p className="px-5 pb-2 text-sm text-argus-danger" role="alert">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3 border-t border-argus-border-subtle px-5 py-4">
        {sourceCount > 0 ? (
          <button
            type="button"
            onClick={() => setPanel("sources")}
            className="flex items-center gap-1.5 text-xs text-argus-tertiary transition-colors duration-150 hover:text-argus-secondary"
          >
            <PaperclipIcon className="shrink-0" />
            {sourceCount} source{sourceCount !== 1 ? "s" : ""} attached
          </button>
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={loading || !query.trim()}
          className="ml-auto flex h-10 items-center gap-2 rounded-[10px] bg-ink px-5 text-sm font-semibold text-white transition-colors duration-150 hover:bg-ink-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? (
            <>
              <Spinner />
              Preparing…
            </>
          ) : (
            "Start analysis"
          )}
        </button>
      </div>
    </div>
  );
}
