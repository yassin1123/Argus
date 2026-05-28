"use client";

// Pilot onboarding wizard — Phase 5 / Week 24 / Day 2.
//
// A four-step guided flow a firm_admin runs on a fresh firm:
//   1. Firm setup    — name + branding
//   2. Invite team   — partner + 1-3 members
//   3. Upload library— the firm's OWN files (W14 ingestion)
//   4. First engagement — brief + mode + lead + reviewer
//
// Progress is read from /api/onboarding/status on mount so the flow
// can be paused and resumed (and reflects setup done out-of-band via
// the operator CLI). Every step has a Skip button for operator-
// assisted setup where some steps are handled offline.

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { uploadFirmContent, type FirmContentCategory } from "@/lib/api/firmLibrary";
import {
  createFirstEngagement,
  getOnboardingStatus,
  getTemplateBriefs,
  inviteTeamMember,
  setFirmBranding,
  type OnboardingStatus,
  type PilotBrief,
} from "@/lib/api/onboarding";

type StepKey = "firm_setup" | "invite_team" | "upload_library" | "first_engagement";

const STEPS: { key: StepKey; label: string }[] = [
  { key: "firm_setup", label: "Firm setup" },
  { key: "invite_team", label: "Invite team" },
  { key: "upload_library", label: "Upload library" },
  { key: "first_engagement", label: "First engagement" },
];

const MODES = [
  { id: "m_and_a_diligence", label: "M&A diligence" },
  { id: "growth_strategy", label: "Growth strategy" },
  { id: "general", label: "General decision support" },
];

const LIBRARY_CATEGORIES: FirmContentCategory[] = [
  "playbook",
  "sector_primer",
  "prior_report",
  "framework",
  "methodology",
  "other",
];

interface FileUpload {
  file: File;
  status: "pending" | "uploading" | "ready" | "dedup_skipped" | "failed";
  detail?: string;
}

export default function PilotOnboardingWizard() {
  const [stepIdx, setStepIdx] = useState(0);
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getOnboardingStatus();
      setStatus(s);
      return s;
    } catch (e) {
      setBanner({ kind: "err", msg: (e as Error).message });
      return null;
    }
  }, []);

  // Resume: land on the first incomplete step.
  useEffect(() => {
    (async () => {
      const s = await refreshStatus();
      if (s) {
        const firstIncomplete = STEPS.findIndex((st) => !s.steps[st.key]);
        setStepIdx(firstIncomplete === -1 ? STEPS.length - 1 : firstIncomplete);
      }
      setLoading(false);
    })();
  }, [refreshStatus]);

  const goNext = () => setStepIdx((i) => Math.min(i + 1, STEPS.length - 1));
  const goTo = (i: number) => setStepIdx(i);

  const onStepComplete = async (msg: string) => {
    setBanner({ kind: "ok", msg });
    await refreshStatus();
    goNext();
  };

  if (loading) {
    return <div className="p-8 text-sm text-argus-secondary">Loading onboarding…</div>;
  }

  const current = STEPS[stepIdx];

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-argus-primary">
          Welcome to Argus{status?.name ? ` — ${status.name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-argus-secondary">
          Four steps to your first engagement. You can pause anytime and pick up
          where you left off.
        </p>
      </header>

      <ProgressBar steps={STEPS} stepIdx={stepIdx} status={status} onJump={goTo} />

      {banner && (
        <div
          role="status"
          className={`mt-4 rounded-argus px-4 py-2 text-sm ${
            banner.kind === "ok"
              ? "bg-emerald-50 text-emerald-800"
              : "bg-red-50 text-red-800"
          }`}
        >
          {banner.msg}
        </div>
      )}

      <section className="mt-6 rounded-argus border border-argus-border-subtle bg-surface p-6">
        {current.key === "firm_setup" && (
          <FirmSetupStep onDone={() => onStepComplete("Firm branding saved.")} />
        )}
        {current.key === "invite_team" && (
          <InviteTeamStep onDone={() => onStepComplete("Team updated.")} />
        )}
        {current.key === "upload_library" && status && (
          <UploadLibraryStep firmId={status.firm_id} onDone={() => onStepComplete("Library updated.")} />
        )}
        {current.key === "first_engagement" && (
          <FirstEngagementStep onDone={() => onStepComplete("First engagement created.")} />
        )}

        <div className="mt-6 flex items-center justify-between">
          <Button
            variant="ghost"
            disabled={stepIdx === 0}
            onClick={() => goTo(Math.max(0, stepIdx - 1))}
          >
            Back
          </Button>
          <button
            type="button"
            className="text-sm text-argus-secondary underline hover:text-argus-primary"
            onClick={goNext}
          >
            Skip this step
          </button>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

function ProgressBar({
  steps,
  stepIdx,
  status,
  onJump,
}: {
  steps: { key: StepKey; label: string }[];
  stepIdx: number;
  status: OnboardingStatus | null;
  onJump: (i: number) => void;
}) {
  return (
    <ol className="flex items-center gap-2" aria-label="Onboarding progress">
      {steps.map((s, i) => {
        const done = status?.steps[s.key];
        const active = i === stepIdx;
        return (
          <li key={s.key} className="flex-1">
            <button
              type="button"
              onClick={() => onJump(i)}
              className={`w-full rounded-argus border px-3 py-2 text-left text-xs font-medium transition-colors ${
                active
                  ? "border-argus-accent bg-elevated text-argus-primary"
                  : done
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                    : "border-argus-border-subtle text-argus-secondary hover:bg-elevated"
              }`}
            >
              <span className="block">
                {done ? "✓ " : `${i + 1}. `}
                {s.label}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — firm setup
// ---------------------------------------------------------------------------

function FirmSetupStep({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#0B3D2E");
  const [footerText, setFooterText] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await setFirmBranding({
        name: name.trim() || undefined,
        primary_color: primaryColor || undefined,
        footer_text: footerText.trim() || undefined,
        logo_url: logoUrl.trim() || undefined,
      });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2 className="text-base font-semibold text-argus-primary">Firm setup</h2>
      <p className="mt-1 text-sm text-argus-secondary">
        Your branding flows through to every client-facing deliverable.
      </p>
      <div className="mt-4 space-y-3">
        <Field label="Firm name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Blackmont Consulting" />
        </Field>
        <Field label="Primary color">
          <div className="flex items-center gap-2">
            <input type="color" value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} className="h-9 w-12 rounded border border-argus-border-subtle" />
            <input className={inputCls} value={primaryColor} onChange={(e) => setPrimaryColor(e.target.value)} />
          </div>
        </Field>
        <Field label="Footer text (client documents)">
          <input className={inputCls} value={footerText} onChange={(e) => setFooterText(e.target.value)} placeholder="Blackmont Consulting — Private & Confidential" />
        </Field>
        <Field label="Logo URL (optional)">
          <input className={inputCls} value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://…" />
        </Field>
      </div>
      {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
      <Button className="mt-4" onClick={submit} disabled={busy}>
        {busy ? "Saving…" : "Save & continue"}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — invite team
// ---------------------------------------------------------------------------

function InviteTeamStep({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"firm_admin" | "firm_member">("firm_member");
  const [invited, setInvited] = useState<{ email: string; role: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const addOne = async () => {
    if (!email.trim() || !name.trim()) {
      setErr("Email and name are required.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await inviteTeamMember({ email: email.trim(), name: name.trim(), role });
      setInvited((xs) => [...xs, { email: email.trim(), role }]);
      setEmail("");
      setName("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2 className="text-base font-semibold text-argus-primary">Invite your team</h2>
      <p className="mt-1 text-sm text-argus-secondary">
        Add a partner and 1–3 consultants or analysts.
      </p>
      <div className="mt-4 grid grid-cols-[1fr_1fr_auto] gap-2">
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" />
        <input className={inputCls} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@firm.com" />
        <select className={inputCls} value={role} onChange={(e) => setRole(e.target.value as "firm_admin" | "firm_member")}>
          <option value="firm_member">Member</option>
          <option value="firm_admin">Admin</option>
        </select>
      </div>
      {err && <p className="mt-2 text-sm text-red-700">{err}</p>}
      <Button className="mt-3" variant="outline" onClick={addOne} disabled={busy}>
        {busy ? "Adding…" : "Add member"}
      </Button>

      {invited.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm text-argus-secondary">
          {invited.map((m, i) => (
            <li key={i}>
              ✓ {m.email} ({m.role === "firm_admin" ? "Admin" : "Member"})
            </li>
          ))}
        </ul>
      )}

      <Button className="mt-4" onClick={onDone}>
        Continue
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — upload library
// ---------------------------------------------------------------------------

function UploadLibraryStep({ firmId, onDone }: { firmId: string; onDone: () => void }) {
  const [category, setCategory] = useState<FirmContentCategory>("playbook");
  const [modes, setModes] = useState<string[]>([]);
  const [files, setFiles] = useState<FileUpload[]>([]);
  const [busy, setBusy] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    setFiles((xs) => [
      ...xs,
      ...Array.from(list).map((file) => ({ file, status: "pending" as const })),
    ]);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  };

  const toggleMode = (m: string) =>
    setModes((xs) => (xs.includes(m) ? xs.filter((x) => x !== m) : [...xs, m]));

  const uploadAll = async () => {
    setBusy(true);
    for (let i = 0; i < files.length; i++) {
      if (files[i].status === "ready" || files[i].status === "dedup_skipped") continue;
      setFiles((xs) => xs.map((f, j) => (j === i ? { ...f, status: "uploading" } : f)));
      try {
        const res = await uploadFirmContent(firmId, {
          title: files[i].file.name.replace(/\.[^.]+$/, ""),
          category,
          intendedModes: modes,
          file: files[i].file,
        });
        const cached = res.ingest.cached;
        setFiles((xs) =>
          xs.map((f, j) =>
            j === i
              ? {
                  ...f,
                  status: cached ? "dedup_skipped" : "ready",
                  detail: cached
                    ? "already in library"
                    : `${res.ingest.chunks_written} chunks`,
                }
              : f,
          ),
        );
      } catch (e) {
        setFiles((xs) =>
          xs.map((f, j) => (j === i ? { ...f, status: "failed", detail: (e as Error).message } : f)),
        );
      }
    }
    setBusy(false);
  };

  return (
    <div>
      <h2 className="text-base font-semibold text-argus-primary">Upload your library</h2>
      <p className="mt-1 text-sm text-argus-secondary">
        Your own playbooks, sector primers, methodologies, and prior reports.
        PDF, Word, Markdown, or text. We never seed sample content into your firm.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <Field label="Category">
          <select className={inputCls} value={category} onChange={(e) => setCategory(e.target.value as FirmContentCategory)}>
            {LIBRARY_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Intended modes (optional)">
          <div className="flex flex-wrap gap-1">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => toggleMode(m.id)}
                className={`rounded-argus border px-2 py-1 text-xs ${
                  modes.includes(m.id)
                    ? "border-argus-accent bg-elevated text-argus-primary"
                    : "border-argus-border-subtle text-argus-secondary"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </Field>
      </div>

      <div
        ref={dropRef}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="mt-4 rounded-argus border-2 border-dashed border-argus-border-subtle p-6 text-center"
      >
        <p className="text-sm text-argus-secondary">Drag files here, or</p>
        <label className="mt-2 inline-block cursor-pointer text-sm font-medium text-argus-accent underline">
          choose files
          <input type="file" multiple className="hidden" onChange={(e) => addFiles(e.target.files)} />
        </label>
      </div>

      {files.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between">
              <span className="text-argus-primary">{f.file.name}</span>
              <span className={statusColor(f.status)}>
                {f.status}
                {f.detail ? ` — ${f.detail}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex gap-2">
        <Button variant="outline" onClick={uploadAll} disabled={busy || files.length === 0}>
          {busy ? "Uploading…" : "Upload files"}
        </Button>
        <Button onClick={onDone}>Continue</Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — first engagement
// ---------------------------------------------------------------------------

function FirstEngagementStep({ onDone }: { onDone: () => void }) {
  const [brief, setBrief] = useState("");
  const [mode, setMode] = useState("m_and_a_diligence");
  const [leadEmail, setLeadEmail] = useState("");
  const [reviewerEmail, setReviewerEmail] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [briefs, setBriefs] = useState<PilotBrief[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const res = await getTemplateBriefs(mode);
        setBriefs(res.modes[mode] || []);
      } catch {
        setBriefs([]);
      }
    })();
  }, [mode]);

  const submit = async () => {
    if (brief.trim().length < 10 || !leadEmail.trim()) {
      setErr("A brief and a lead email are required.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await createFirstEngagement({
        brief: brief.trim(),
        mode,
        lead_email: leadEmail.trim(),
        reviewer_email: reviewerEmail.trim() || undefined,
        title: title.trim() || undefined,
      });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2 className="text-base font-semibold text-argus-primary">Your first engagement</h2>
      <p className="mt-1 text-sm text-argus-secondary">
        Write a brief, pick a mode, and assign a lead and reviewer.
      </p>

      <div className="mt-4 space-y-3">
        <Field label="Mode">
          <select className={inputCls} value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>

        {briefs.length > 0 && (
          <details className="rounded-argus border border-argus-border-subtle p-3">
            <summary className="cursor-pointer text-sm font-medium text-argus-secondary">
              See {briefs.length} example brief{briefs.length > 1 ? "s" : ""} for this mode
            </summary>
            <ul className="mt-2 space-y-2">
              {briefs.map((b) => (
                <li key={b.id} className="text-sm">
                  <button
                    type="button"
                    className="text-left text-argus-accent underline"
                    onClick={() => {
                      setBrief(b.body);
                      setTitle(b.title);
                    }}
                  >
                    {b.title}
                  </button>
                  <span className="block text-xs text-argus-secondary">{b.why_good}</span>
                </li>
              ))}
            </ul>
          </details>
        )}

        <Field label="Brief">
          <textarea
            className={`${inputCls} min-h-[140px]`}
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            placeholder="Describe the decision to support, the evidence you have, and the questions that matter…"
          />
        </Field>
        <Field label="Engagement title (optional)">
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Lead (email)">
            <input className={inputCls} value={leadEmail} onChange={(e) => setLeadEmail(e.target.value)} placeholder="lead@firm.com" />
          </Field>
          <Field label="Reviewer (email, optional)">
            <input className={inputCls} value={reviewerEmail} onChange={(e) => setReviewerEmail(e.target.value)} placeholder="reviewer@firm.com" />
          </Field>
        </div>
      </div>

      {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
      <Button className="mt-4" onClick={submit} disabled={busy}>
        {busy ? "Creating…" : "Create engagement"}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small shared bits
// ---------------------------------------------------------------------------

const inputCls =
  "w-full rounded-argus border border-argus-border-subtle bg-surface px-3 py-2 text-sm text-argus-primary focus:border-argus-accent focus:outline-none";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-argus-secondary">{label}</span>
      {children}
    </label>
  );
}

function statusColor(s: FileUpload["status"]): string {
  switch (s) {
    case "ready":
      return "text-emerald-700";
    case "dedup_skipped":
      return "text-amber-700";
    case "failed":
      return "text-red-700";
    case "uploading":
      return "text-argus-accent";
    default:
      return "text-argus-secondary";
  }
}
