"use client";

import { useEffect, useId, useRef, useState } from "react";

import {
  type FirmContent,
  type FirmContentCategory,
  uploadFirmContent,
} from "@/lib/api/firmLibrary";

// Mirrors the backend allowlist in
// backend/core/firm_library/service.py:SUPPORTED_EXTENSIONS.
const ACCEPTED_EXT = ".pdf,.docx,.md,.txt";
const MAX_BYTES = 50 * 1024 * 1024; // 50 MB — matches the existing engagement upload cap.
const MAX_DESCRIPTION = 500;

const CATEGORIES: { value: FirmContentCategory; label: string; hint: string }[] = [
  { value: "playbook", label: "Playbook", hint: "Repeatable methodology, e.g. M&A target screen" },
  { value: "sector_primer", label: "Sector primer", hint: "Industry context the firm uses across deals" },
  { value: "prior_report", label: "Prior report", hint: "Past engagement deliverable, anonymised" },
  { value: "framework", label: "Framework", hint: "Decision/diagnostic structure, e.g. 2x2, value chain" },
  { value: "methodology", label: "Methodology", hint: "Internal process — diligence checklist, etc." },
  { value: "other", label: "Other", hint: "" },
];

// Mirrors backend/config/consulting_modes.yaml. Keeping this hard-coded
// for Day 2; Day 3 may pull it from a /api/modes endpoint if more modes
// land. The spec said to match the planner-prompt mode names exactly.
const CONSULTING_MODES: { value: string; label: string }[] = [
  { value: "general", label: "General" },
  { value: "market_entry", label: "Market entry" },
  { value: "due_diligence", label: "Due diligence" },
  { value: "growth_strategy", label: "Growth strategy" },
];

// Common sector chips. The chips field accepts free-form additions, so this
// list is just a starting palette.
const SUGGESTED_SECTORS = [
  "Retail",
  "Fintech",
  "Healthcare",
  "Energy",
  "Industrial",
  "Tech",
  "Consumer",
  "B2B SaaS",
];

type Phase = "idle" | "uploading" | "success" | "error";

function isAllowedFilename(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXT.split(",").some((ext) => lower.endsWith(ext));
}

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

function stemOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(0, dot) : filename;
}

export interface UploadPanelProps {
  firmId: string;
  onUploaded?: (content: FirmContent) => void;
}

export default function UploadPanel({ firmId, onUploaded }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [titleEdited, setTitleEdited] = useState(false);
  const [category, setCategory] = useState<FirmContentCategory | "">("");
  const [description, setDescription] = useState("");
  const [modes, setModes] = useState<string[]>([]);
  const [sectorChips, setSectorChips] = useState<string[]>([]);
  const [sectorDraft, setSectorDraft] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const titleId = useId();
  const categoryId = useId();
  const descId = useId();
  const sectorInputId = useId();

  // When the user changes the file before manually editing the title,
  // default the title to the file's stem. Once they type their own
  // title, we stop overwriting it.
  useEffect(() => {
    if (file && !titleEdited) {
      setTitle(stemOf(file.name));
    }
  }, [file, titleEdited]);

  const reset = () => {
    setFile(null);
    setTitle("");
    setTitleEdited(false);
    setCategory("");
    setDescription("");
    setModes([]);
    setSectorChips([]);
    setSectorDraft("");
    setPhase("idle");
    setErrorMsg(null);
  };

  const handleSelectFile = (chosen: File | null) => {
    if (!chosen) return;
    if (!isAllowedFilename(chosen.name)) {
      setErrorMsg(
        `Unsupported file type. Argus accepts ${ACCEPTED_EXT.replaceAll(".", "").replaceAll(",", ", ")}.`,
      );
      setFile(null);
      return;
    }
    if (chosen.size > MAX_BYTES) {
      setErrorMsg(`File too large (${fmtBytes(chosen.size)}). Max ${fmtBytes(MAX_BYTES)}.`);
      setFile(null);
      return;
    }
    setErrorMsg(null);
    setSuccessMsg(null);
    setFile(chosen);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0] ?? null;
    handleSelectFile(f);
  };

  const onAddSectorFromDraft = () => {
    const v = sectorDraft.trim();
    if (!v) return;
    if (!sectorChips.includes(v)) setSectorChips((prev) => [...prev, v]);
    setSectorDraft("");
  };

  const onSectorKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      onAddSectorFromDraft();
    } else if (e.key === "Backspace" && !sectorDraft && sectorChips.length > 0) {
      setSectorChips((prev) => prev.slice(0, -1));
    }
  };

  const removeSector = (s: string) => {
    setSectorChips((prev) => prev.filter((x) => x !== s));
  };

  const toggleMode = (m: string) => {
    setModes((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));
  };

  const submitDisabled =
    phase === "uploading" || !file || !title.trim() || !category;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitDisabled || !file || !category) return;
    setPhase("uploading");
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const result = await uploadFirmContent(firmId, {
        title: title.trim(),
        category,
        description: description.trim() || undefined,
        intendedModes: modes,
        sectorTags: sectorChips,
        file,
      });
      setPhase("success");
      const cachedNote = result.ingest.cached ? " (already in library — reused)" : "";
      setSuccessMsg(
        `Added "${result.firm_content.title}" — ${result.ingest.chunks_written} chunks indexed${cachedNote}.`,
      );
      onUploaded?.(result.firm_content);
      // Reset form fields but keep success toast visible.
      setFile(null);
      setTitle("");
      setTitleEdited(false);
      setCategory("");
      setDescription("");
      setModes([]);
      setSectorChips([]);
      setSectorDraft("");
      if (inputRef.current) inputRef.current.value = "";
    } catch (e) {
      setPhase("error");
      setErrorMsg(e instanceof Error ? e.message : "Upload failed.");
    }
  };

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-5 rounded-argus-md border border-argus-border-subtle bg-surface p-5"
      data-testid="firm-library-upload-form"
    >
      {/* Drag-drop / file picker */}
      <div>
        <label className="argus-label mb-2 block">File</label>
        <div
          onClick={() => inputRef.current?.click()}
          onDrop={onDrop}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          role="button"
          tabIndex={0}
          aria-label="Upload file"
          className={`flex cursor-pointer flex-col items-center justify-center rounded-sm border-2 border-dashed px-4 py-8 text-center text-[13px] transition-colors ${
            dragOver
              ? "border-argus-accent bg-elevated"
              : "border-argus-border-moderate hover:border-argus-border-strong"
          }`}
        >
          {file ? (
            <div className="flex flex-col items-center gap-1">
              <span className="font-mono text-[12px] text-argus-primary">{file.name}</span>
              <span className="text-[11px] text-argus-tertiary">
                {fmtBytes(file.size)} —{" "}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                    setTitleEdited(false);
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                  className="text-argus-accent hover:underline"
                >
                  remove
                </button>
              </span>
            </div>
          ) : (
            <>
              <span className="text-argus-secondary">Drop a file or click to browse</span>
              <span className="mt-1 text-[11px] text-argus-tertiary">
                PDF, DOCX, MD, TXT — up to {fmtBytes(MAX_BYTES)}
              </span>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXT}
            className="sr-only"
            data-testid="firm-library-file-input"
            onChange={(e) => handleSelectFile(e.target.files?.[0] ?? null)}
          />
        </div>
      </div>

      {/* Title */}
      <div>
        <label htmlFor={titleId} className="argus-label mb-2 block">
          Title <span className="text-argus-contested">*</span>
        </label>
        <input
          id={titleId}
          type="text"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setTitleEdited(true);
          }}
          maxLength={512}
          required
          className="w-full rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 text-[13px] focus:border-argus-border-strong focus:outline-none"
          placeholder="e.g. M&A target screen — payments"
        />
      </div>

      {/* Category */}
      <div>
        <label htmlFor={categoryId} className="argus-label mb-2 block">
          Category <span className="text-argus-contested">*</span>
        </label>
        <select
          id={categoryId}
          value={category}
          onChange={(e) => setCategory(e.target.value as FirmContentCategory)}
          required
          className="w-full rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 text-[13px] focus:border-argus-border-strong focus:outline-none"
        >
          <option value="">Select a category…</option>
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
              {c.hint ? ` — ${c.hint}` : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Description */}
      <div>
        <label htmlFor={descId} className="argus-label mb-2 block">
          Description{" "}
          <span className="text-argus-tertiary">(optional)</span>
        </label>
        <textarea
          id={descId}
          value={description}
          onChange={(e) => setDescription(e.target.value.slice(0, MAX_DESCRIPTION))}
          rows={3}
          className="w-full resize-y rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 text-[13px] focus:border-argus-border-strong focus:outline-none"
          placeholder="One or two sentences on when consultants should pull this."
        />
        <div className="mt-1 text-right font-mono text-[10px] tabular-nums text-argus-tertiary">
          {description.length}/{MAX_DESCRIPTION}
        </div>
      </div>

      {/* Intended modes */}
      <div>
        <span className="argus-label mb-2 block">
          Intended modes <span className="text-argus-tertiary">(optional)</span>
        </span>
        <div className="flex flex-wrap gap-1.5">
          {CONSULTING_MODES.map((m) => {
            const active = modes.includes(m.value);
            return (
              <button
                key={m.value}
                type="button"
                onClick={() => toggleMode(m.value)}
                aria-pressed={active}
                className={`rounded-sm border px-2 py-1 text-[12px] transition-colors ${
                  active
                    ? "border-argus-primary bg-argus-primary text-argus-inverse"
                    : "border-argus-border-subtle bg-surface text-argus-secondary hover:border-argus-border-moderate"
                }`}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Sector tags */}
      <div>
        <label htmlFor={sectorInputId} className="argus-label mb-2 block">
          Sector tags <span className="text-argus-tertiary">(optional)</span>
        </label>
        <div className="flex flex-wrap items-center gap-1.5 rounded-sm border border-argus-border-moderate bg-surface px-2 py-1.5">
          {sectorChips.map((s) => (
            <span
              key={s}
              className="inline-flex items-center gap-1 rounded-sm border border-argus-border-subtle bg-elevated px-1.5 py-0.5 text-[11px] text-argus-primary"
            >
              {s}
              <button
                type="button"
                onClick={() => removeSector(s)}
                aria-label={`Remove ${s}`}
                className="text-argus-tertiary hover:text-argus-contested"
              >
                ×
              </button>
            </span>
          ))}
          <input
            id={sectorInputId}
            type="text"
            value={sectorDraft}
            onChange={(e) => setSectorDraft(e.target.value)}
            onKeyDown={onSectorKeyDown}
            onBlur={onAddSectorFromDraft}
            placeholder={sectorChips.length === 0 ? "Add tags (Enter or comma to add)" : ""}
            className="min-w-[120px] flex-1 bg-transparent text-[12px] focus:outline-none"
          />
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          {SUGGESTED_SECTORS.filter((s) => !sectorChips.includes(s)).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSectorChips((prev) => [...prev, s])}
              className="rounded-sm px-1 py-0.5 text-[11px] text-argus-tertiary hover:text-argus-primary"
            >
              + {s}
            </button>
          ))}
        </div>
      </div>

      {/* Status messages */}
      {errorMsg ? (
        <div
          role="alert"
          className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested"
        >
          {errorMsg}
        </div>
      ) : null}
      {successMsg ? (
        <div
          role="status"
          className="rounded-sm border border-argus-firm-border bg-argus-firm-bg px-2 py-1 text-[12px] text-argus-firm"
        >
          {successMsg}
        </div>
      ) : null}

      {/* Submit */}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitDisabled}
          className={`rounded-sm px-3 py-1.5 text-[12px] font-semibold transition-colors ${
            submitDisabled
              ? "cursor-not-allowed border border-argus-border-subtle bg-elevated text-argus-tertiary"
              : "bg-argus-primary text-argus-inverse hover:opacity-90"
          }`}
        >
          {phase === "uploading" ? "Indexing…" : "Add to library"}
        </button>
        {phase === "uploading" ? (
          <span className="text-[11px] text-argus-tertiary">
            Parsing, chunking, and embedding. PDFs of 50+ pages can take 5–30s.
          </span>
        ) : null}
        {phase !== "uploading" && (file || title || category) ? (
          <button
            type="button"
            onClick={reset}
            className="text-[12px] text-argus-tertiary hover:text-argus-primary"
          >
            Reset
          </button>
        ) : null}
      </div>
    </form>
  );
}
