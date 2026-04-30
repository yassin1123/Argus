"use client";

import { useRef, useState } from "react";

import { patchSource, submitUrl, uploadFile } from "@/lib/api";
import type { SourceScope, TrustLevel } from "@/lib/types";

const TRUST_TONE: Record<TrustLevel, string> = {
  firm_vetted: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  credible_external: "border-argus-credible-border bg-argus-credible-bg text-argus-credible",
  web_general: "border-argus-web-border bg-argus-web-bg text-argus-web",
  contested: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

const TRUST_LABEL: Record<TrustLevel, string> = {
  firm_vetted: "Firm-vetted",
  credible_external: "Credible external",
  web_general: "Web-general",
  contested: "Contested",
};

const TRUST_HINT: Record<TrustLevel, string> = {
  firm_vetted: "Internal / pre-approved",
  credible_external: "FT / peer-review",
  web_general: "Public web",
  contested: "Single-source / disputed",
};

const ACCEPT_EXT = ".pdf,.csv,.json";
const MAX_BYTES = 50 * 1024 * 1024;

type Phase = "Queued" | "Uploading" | "Submitted" | "Tagging" | "Done" | "Failed";

interface UploadJob {
  id: string;
  kind: "file" | "url";
  label: string;
  size?: number;
  phase: Phase;
  error?: string;
}

function CloseIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

function UploadIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M17 8l-5-5-5 5M12 3v12" />
    </svg>
  );
}

function PhaseDot({ phase }: { phase: Phase }) {
  const cls =
    phase === "Done"
      ? "bg-argus-firm"
      : phase === "Failed"
        ? "bg-argus-contested"
        : "bg-argus-web animate-pulse";
  return <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${cls}`} />;
}

function fmtBytes(b: number): string {
  if (b < 1024) return `${b}B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)}KB`;
  return `${(b / 1024 / 1024).toFixed(1)}MB`;
}

export default function AddSourcePanel({
  engagementId,
  open,
  onClose,
  onAdded,
}: {
  engagementId: string;
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [tab, setTab] = useState<"upload" | "url">("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [urlText, setUrlText] = useState("");
  const [trust, setTrust] = useState<TrustLevel>("credible_external");
  const [scope, setScope] = useState<SourceScope>("engagement");
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  if (!open) return null;

  const reset = () => {
    setFiles([]);
    setUrlText("");
    setError(null);
    setJobs([]);
  };

  const acceptFiles = (incoming: FileList | File[]) => {
    const list = Array.from(incoming);
    const filtered: File[] = [];
    for (const f of list) {
      if (f.size > MAX_BYTES) {
        setError(`${f.name} exceeds the 50MB limit and was skipped.`);
        continue;
      }
      filtered.push(f);
    }
    setFiles((prev) => [...prev, ...filtered]);
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const updateJob = (id: string, patch: Partial<UploadJob>) => {
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)));
  };

  const applyTagsAfterUpload = async (sourceId: string) => {
    const patches: Parameters<typeof patchSource>[1] = {};
    // Trust default is credible_external; only patch if user changed it.
    if (trust !== "credible_external") patches.trust_level = trust;
    if (scope === "firm") patches.scope = "firm";
    if (Object.keys(patches).length === 0) return;
    await patchSource(sourceId, patches);
  };

  const runUploads = async () => {
    setBusy(true);
    setError(null);
    const initialJobs: UploadJob[] = files.map((f) => ({
      id: `f-${f.name}-${f.size}-${Math.random().toString(36).slice(2, 8)}`,
      kind: "file",
      label: f.name,
      size: f.size,
      phase: "Queued",
    }));
    setJobs(initialJobs);

    let anySuccess = false;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const job = initialJobs[i];
      try {
        updateJob(job.id, { phase: "Uploading" });
        const result = (await uploadFile(engagementId, f)) as { file_id?: string };
        updateJob(job.id, { phase: "Submitted" });
        if (result.file_id && (trust !== "credible_external" || scope === "firm")) {
          updateJob(job.id, { phase: "Tagging" });
          try {
            await applyTagsAfterUpload(result.file_id);
          } catch (e) {
            // Tagging failed but upload succeeded — surface a non-fatal note
            updateJob(job.id, {
              phase: "Done",
              error: e instanceof Error ? `tagged with default: ${e.message}` : "tag step failed",
            });
            anySuccess = true;
            continue;
          }
        }
        updateJob(job.id, { phase: "Done" });
        anySuccess = true;
      } catch (e) {
        updateJob(job.id, {
          phase: "Failed",
          error: e instanceof Error ? e.message : "upload failed",
        });
      }
    }
    setBusy(false);
    if (anySuccess) {
      onAdded();
      setFiles([]);
    }
  };

  const runUrls = async () => {
    setBusy(true);
    setError(null);
    const lines = urlText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (lines.length === 0) {
      setBusy(false);
      setError("Paste at least one URL.");
      return;
    }
    const initialJobs: UploadJob[] = lines.map((u) => ({
      id: `u-${u}-${Math.random().toString(36).slice(2, 8)}`,
      kind: "url",
      label: u,
      phase: "Queued",
    }));
    setJobs(initialJobs);

    let anySuccess = false;
    for (let i = 0; i < lines.length; i++) {
      const u = lines[i];
      const job = initialJobs[i];
      try {
        updateJob(job.id, { phase: "Uploading" });
        const result = (await submitUrl(engagementId, u)) as { file_id?: string };
        updateJob(job.id, { phase: "Submitted" });
        if (result.file_id && (trust !== "credible_external" || scope === "firm")) {
          updateJob(job.id, { phase: "Tagging" });
          try {
            await applyTagsAfterUpload(result.file_id);
          } catch (e) {
            updateJob(job.id, {
              phase: "Done",
              error: e instanceof Error ? `tagged with default: ${e.message}` : "tag step failed",
            });
            anySuccess = true;
            continue;
          }
        }
        updateJob(job.id, { phase: "Done" });
        anySuccess = true;
      } catch (e) {
        updateJob(job.id, {
          phase: "Failed",
          error: e instanceof Error ? e.message : "fetch failed",
        });
      }
    }
    setBusy(false);
    if (anySuccess) {
      onAdded();
      setUrlText("");
    }
  };

  const handleSubmit = () => {
    if (tab === "upload") void runUploads();
    else void runUrls();
  };

  const canSubmit =
    !busy &&
    (tab === "upload" ? files.length > 0 : urlText.trim().length > 0);

  return (
    <>
      <div aria-hidden onClick={busy ? undefined : onClose} className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" />
      <aside
        role="dialog"
        aria-label="Add source"
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col overflow-hidden border-l border-argus-border-subtle bg-canvas shadow-argus-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-argus-border-subtle bg-surface px-5 py-4">
          <div>
            <div className="argus-label">Add source</div>
            <h2 className="mt-1 font-serif text-[18px] font-semibold text-argus-primary">
              Upload a file or paste a URL
            </h2>
            <p className="mt-1 text-[12px] leading-snug text-argus-tertiary">
              Pick a trust tier — citations rendered from this source will inherit the badge.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="rounded-argus-sm p-1 text-argus-tertiary transition-colors hover:bg-elevated hover:text-argus-primary disabled:opacity-50"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        {/* Tabs */}
        <div className="flex border-b border-argus-border-subtle bg-surface px-5 text-[11px]">
          {(["upload", "url"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`-mb-px border-b-2 px-3 py-2 transition-colors ${
                tab === t
                  ? "border-argus-primary font-semibold text-argus-primary"
                  : "border-transparent text-argus-tertiary hover:text-argus-secondary"
              }`}
            >
              {t === "upload" ? "Upload file" : "Paste URL"}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {tab === "upload" ? (
            <>
              {/* Drop zone */}
              <div
                onDragEnter={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  if (e.dataTransfer.files.length > 0) acceptFiles(e.dataTransfer.files);
                }}
                onClick={() => inputRef.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    inputRef.current?.click();
                  }
                }}
                className={`flex h-36 cursor-pointer flex-col items-center justify-center gap-2 rounded-argus-md border-2 border-dashed text-center transition-colors ${
                  dragOver
                    ? "border-argus-primary bg-argus-credible-bg/40"
                    : "border-argus-border-moderate bg-surface hover:border-argus-primary"
                }`}
              >
                <UploadIcon className="h-6 w-6 text-argus-tertiary" />
                <div className="font-serif text-[14px] text-argus-primary">
                  {dragOver ? "Drop to upload" : "Drag files here or click to choose"}
                </div>
                <div className="text-[11px] text-argus-tertiary">
                  PDF · CSV · JSON · up to 50MB
                </div>
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept={ACCEPT_EXT}
                  onChange={(e) => {
                    if (e.target.files) acceptFiles(e.target.files);
                    e.target.value = "";
                  }}
                  className="sr-only"
                />
              </div>

              {/* Selected files queue */}
              {files.length > 0 ? (
                <ul className="mt-3 divide-y divide-argus-border-subtle/60 rounded-sm border border-argus-border-subtle bg-surface text-[12px]">
                  {files.map((f, i) => (
                    <li key={`${f.name}-${i}`} className="flex items-center gap-2 px-2 py-1.5">
                      <span className="min-w-0 flex-1 truncate font-medium text-argus-primary">{f.name}</span>
                      <span className="font-mono text-[10px] tabular-nums text-argus-tertiary">{fmtBytes(f.size)}</span>
                      <button
                        type="button"
                        onClick={() => removeFile(i)}
                        aria-label={`Remove ${f.name}`}
                        className="rounded-sm p-0.5 text-argus-tertiary hover:bg-elevated hover:text-argus-contested"
                      >
                        <CloseIcon className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <div>
              <label htmlFor="url" className="argus-label mb-1 block">
                Public URL(s)
              </label>
              <textarea
                id="url"
                value={urlText}
                rows={4}
                onChange={(e) => setUrlText(e.target.value)}
                placeholder={"https://www.bitkom.org/article-1\nhttps://www.numeum.fr/report-2024"}
                className="w-full resize-y rounded-sm border border-argus-border-moderate bg-surface px-2.5 py-2 text-[12px] leading-snug placeholder:text-argus-quaternary focus:border-argus-border-strong focus:outline-none"
              />
              <p className="mt-1 text-[11px] text-argus-tertiary">
                One URL per line. Argus fetches each page server-side and chunks the body content.
              </p>
            </div>
          )}

          {/* Trust tier */}
          <div className="mt-5">
            <div className="argus-label mb-2">Trust tier</div>
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(TRUST_LABEL) as TrustLevel[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTrust(t)}
                  className={`rounded-sm border px-2 py-1.5 text-left text-[11px] transition-all ${
                    trust === t
                      ? `${TRUST_TONE[t]} ring-2 ring-offset-1 ring-argus-accent`
                      : "border-argus-border-subtle bg-surface text-argus-secondary hover:border-argus-border-moderate"
                  }`}
                >
                  <div className="font-semibold">{TRUST_LABEL[t]}</div>
                  <div className="text-[10px] opacity-80">{TRUST_HINT[t]}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Scope */}
          <div className="mt-5">
            <div className="argus-label mb-2">Scope</div>
            <div className="flex rounded-sm border border-argus-border-subtle bg-surface p-0.5 text-[11px]">
              {(["engagement", "firm"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setScope(s)}
                  className={`flex-1 rounded-sm px-2 py-1 transition-colors ${
                    scope === s
                      ? "bg-argus-primary text-argus-inverse"
                      : "text-argus-secondary hover:text-argus-primary"
                  }`}
                >
                  {s === "engagement" ? "This engagement" : "Firm-wide library"}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[10px] text-argus-tertiary">
              {scope === "firm"
                ? "Lead role required to promote to firm-wide. The source will appear in /library."
                : "Only this engagement can use this source."}
            </p>
          </div>

          {/* Job queue */}
          {jobs.length > 0 ? (
            <ul className="mt-5 divide-y divide-argus-border-subtle/60 rounded-sm border border-argus-border-subtle bg-surface text-[11px]">
              {jobs.map((j) => (
                <li key={j.id} className="flex items-center gap-2 px-2 py-1.5">
                  <PhaseDot phase={j.phase} />
                  <span className="min-w-0 flex-1 truncate text-argus-primary">{j.label}</span>
                  {j.size ? (
                    <span className="font-mono text-[10px] tabular-nums text-argus-tertiary">{fmtBytes(j.size)}</span>
                  ) : null}
                  <span
                    className={`font-mono text-[10px] tabular-nums ${
                      j.phase === "Failed"
                        ? "text-argus-contested"
                        : j.phase === "Done"
                          ? "text-argus-firm"
                          : "text-argus-tertiary"
                    }`}
                    title={j.error}
                  >
                    {j.phase}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          {error ? (
            <p className="mt-4 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
              {error}
            </p>
          ) : null}
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-argus-border-subtle bg-[var(--bg-rail)] p-4">
          <button
            type="button"
            onClick={reset}
            disabled={busy}
            className="rounded-sm border border-argus-border-subtle bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:border-argus-border-moderate disabled:opacity-50"
          >
            Reset
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={handleSubmit}
            className="rounded-sm border border-argus-border-strong bg-argus-primary px-4 py-1.5 text-[13px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
          >
            {busy
              ? "Submitting…"
              : tab === "upload"
                ? files.length > 1
                  ? `Upload ${files.length} files`
                  : "Upload"
                : "Fetch URLs"}
          </button>
        </footer>
      </aside>
    </>
  );
}
