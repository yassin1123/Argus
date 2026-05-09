"use client";

import { useEffect, useId, useMemo, useState } from "react";

import {
  ALLOWED_SOURCE_TYPES,
  ALLOWED_TRUST_TIERS,
  type FirmMode,
  type ModeConfigPayload,
  type ResolvedMode,
  type SourceTypeLiteral,
  type TrustTierLiteral,
  createFirmMode,
  getFirmMode,
  retireFirmMode,
  updateFirmMode,
} from "@/lib/api/firmModes";

const OVERLAY_MAX = 2000;
const SLUG_RE = /^[a-z][a-z0-9_]{2,40}$/;

export type EditPanelMode =
  /** open with the mode's resolved values; if a firm override exists,
      Save = update; if not, Save = create-from-built-in. */
  | { kind: "open_existing"; name: string }
  /** "+ Create custom mode" — empty form, base_mode = null. */
  | { kind: "create_fresh" };

export interface ModeEditPanelProps {
  firmId: string;
  isAdmin: boolean;
  /** List of built-in mode names so the base_mode dropdown can populate
      on the create-from-built-in path. Pulled from the parent's list. */
  builtInNames: string[];
  panelMode: EditPanelMode;
  onClose: () => void;
  onMutated: () => void;
}

/**
 * Form-state mirror of ModeConfigPayload, but with all fields populated
 * (no `undefined`) so the controls are always controlled. We translate
 * out to a payload at save time, dropping fields that match the
 * built-in default. (Today: no diff — we send the full form, the
 * backend only stores the override layer.)
 */
interface FormState {
  display_name: string;
  description: string;
  required_branches: string[];
  reasoning_slots: string[];
  source_priorities_default: SourceTypeLiteral[];
  trust_tier_rules: { source_type: SourceTypeLiteral; tier: TrustTierLiteral }[];
  writer_overlay: string;
  planner_overlay: string;
}

function emptyForm(): FormState {
  return {
    display_name: "",
    description: "",
    required_branches: [],
    reasoning_slots: [],
    source_priorities_default: [],
    trust_tier_rules: [],
    writer_overlay: "",
    planner_overlay: "",
  };
}

function fromResolved(r: ResolvedMode, override: FirmMode | null): FormState {
  // If a firm override exists, prefer its raw config values (so the
  // editor shows what the FIRM has set, not the merged result). If
  // there's no override, seed from the resolved (built-in) values so
  // an admin sees what they're customising.
  const cfg = override?.config ?? null;
  const pick = <T,>(layerVal: T | undefined, resolvedVal: T): T =>
    layerVal !== undefined ? layerVal : resolvedVal;
  return {
    display_name: pick<string>(cfg?.display_name, r.display_name) || "",
    description: pick<string>(cfg?.description, r.description) || "",
    required_branches: pick<string[]>(cfg?.required_branches, r.required_branches) || [],
    reasoning_slots: pick<string[]>(cfg?.reasoning_slots, r.reasoning_slots) || [],
    source_priorities_default:
      (pick<string[]>(cfg?.source_priorities_default, r.source_priorities_default) || []).filter(
        (x): x is SourceTypeLiteral => (ALLOWED_SOURCE_TYPES as readonly string[]).includes(x),
      ),
    trust_tier_rules: Object.entries(
      pick<Record<string, string>>(cfg?.trust_tier_rules, r.trust_tier_rules) || {},
    )
      .filter(
        ([k, v]) =>
          (ALLOWED_SOURCE_TYPES as readonly string[]).includes(k) &&
          (ALLOWED_TRUST_TIERS as readonly string[]).includes(v),
      )
      .map(([k, v]) => ({ source_type: k as SourceTypeLiteral, tier: v as TrustTierLiteral })),
    writer_overlay: pick<string>(cfg?.writer_overlay, r.writer_overlay) || "",
    planner_overlay: pick<string>(cfg?.planner_overlay, r.planner_overlay) || "",
  };
}

function toPayload(f: FormState): ModeConfigPayload {
  const out: ModeConfigPayload = {
    display_name: f.display_name,
    description: f.description,
    required_branches: [...f.required_branches],
    reasoning_slots: [...f.reasoning_slots],
    source_priorities_default: [...f.source_priorities_default],
    trust_tier_rules: Object.fromEntries(f.trust_tier_rules.map((r) => [r.source_type, r.tier])),
    writer_overlay: f.writer_overlay,
    planner_overlay: f.planner_overlay,
  };
  return out;
}

export default function ModeEditPanel(props: ModeEditPanelProps) {
  const { firmId, isAdmin, builtInNames, panelMode, onClose, onMutated } = props;

  const [resolved, setResolved] = useState<ResolvedMode | null>(null);
  const [override, setOverride] = useState<FirmMode | null>(null);
  const [name, setName] = useState("");
  const [baseMode, setBaseMode] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmRetire, setConfirmRetire] = useState(false);

  const isCreateFresh = panelMode.kind === "create_fresh";
  const hasOverride = !!override && !override.retired_at;
  const nameLocked = !isCreateFresh; // Once named, name is immutable.

  useEffect(() => {
    let alive = true;
    void (async () => {
      if (panelMode.kind === "create_fresh") {
        if (!alive) return;
        setName("");
        setBaseMode(null);
        setForm(emptyForm());
        setResolved(null);
        setOverride(null);
        setError(null);
        return;
      }
      try {
        const r = await getFirmMode(firmId, panelMode.name);
        if (!alive) return;
        setResolved(r.resolved);
        setOverride(r.firm_override);
        setName(r.name);
        // Existing firm override keeps its base_mode; otherwise the
        // built-in is implicitly the base_mode for a customisation.
        setBaseMode(r.firm_override?.base_mode ?? r.name);
        setForm(fromResolved(r.resolved, r.firm_override));
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return () => {
      alive = false;
    };
  }, [firmId, panelMode]);

  const onSave = async () => {
    if (!isAdmin) return;
    setError(null);
    if (isCreateFresh) {
      if (!SLUG_RE.test(name)) {
        setError("Mode name must be lowercase, digits, underscores; 3-41 chars.");
        return;
      }
    }
    if (form.writer_overlay.length > OVERLAY_MAX) {
      setError(`writer_overlay is ${form.writer_overlay.length} chars (max ${OVERLAY_MAX}).`);
      return;
    }
    if (form.planner_overlay.length > OVERLAY_MAX) {
      setError(`planner_overlay is ${form.planner_overlay.length} chars (max ${OVERLAY_MAX}).`);
      return;
    }
    setBusy(true);
    try {
      if (panelMode.kind === "create_fresh" || !hasOverride) {
        await createFirmMode(firmId, {
          name: panelMode.kind === "create_fresh" ? name : panelMode.name,
          base_mode: panelMode.kind === "create_fresh" ? baseMode : panelMode.name,
          config: toPayload(form),
        });
      } else {
        await updateFirmMode(firmId, panelMode.name, toPayload(form));
      }
      onMutated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const onRetire = async () => {
    if (!isAdmin || panelMode.kind === "create_fresh") return;
    setBusy(true);
    setError(null);
    try {
      await retireFirmMode(firmId, panelMode.name);
      onMutated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retire failed");
    } finally {
      setBusy(false);
      setConfirmRetire(false);
    }
  };

  const overlay = (cls = "") => (
    <span aria-hidden onClick={onClose} className={`absolute inset-0 bg-black/30 ${cls}`} />
  );

  return (
    <div role="dialog" aria-label="Mode editor" className="fixed inset-0 z-40 flex">
      {overlay()}
      <aside className="relative ml-auto flex h-full w-full max-w-[640px] flex-col overflow-y-auto border-l border-argus-border-moderate bg-surface shadow-xl">
        <header className="sticky top-0 flex items-start justify-between gap-2 border-b border-argus-border-subtle bg-surface p-4">
          <div className="min-w-0">
            <span className="block font-mono text-[11px] uppercase tracking-wide text-argus-tertiary">
              {isCreateFresh ? "New custom mode" : name}
            </span>
            <h2 className="truncate font-serif text-[18px] font-semibold text-argus-primary">
              {form.display_name || (isCreateFresh ? "Untitled" : name)}
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[11px] text-argus-secondary hover:bg-elevated"
          >
            Close
          </button>
        </header>

        <div className="flex-1 space-y-5 p-4">
          {error ? (
            <p className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
              {error}
            </p>
          ) : null}

          <NameAndBase
            isCreateFresh={isCreateFresh}
            nameLocked={nameLocked}
            name={name}
            setName={setName}
            baseMode={baseMode}
            setBaseMode={setBaseMode}
            builtInNames={builtInNames}
          />

          <ScalarField
            label="Display name"
            value={form.display_name}
            onChange={(v) => setForm({ ...form, display_name: v })}
            hint={hintIfDefault(resolved?.display_name, override?.config.display_name)}
            disabled={!isAdmin}
          />
          <ScalarField
            label="Description"
            value={form.description}
            onChange={(v) => setForm({ ...form, description: v })}
            hint={hintIfDefault(resolved?.description, override?.config.description)}
            disabled={!isAdmin}
            multiline
          />

          <ChipSection
            label="Required branches"
            chips={form.required_branches}
            onChange={(next) => setForm({ ...form, required_branches: next })}
            hint={hintList("Built-in", resolved?.required_branches)}
            disabled={!isAdmin}
            placeholder="Add branch and press Enter…"
          />
          <ChipSection
            label="Reasoning slots"
            chips={form.reasoning_slots}
            onChange={(next) => setForm({ ...form, reasoning_slots: next })}
            hint={hintList("Built-in", resolved?.reasoning_slots)}
            disabled={!isAdmin}
            placeholder="Add slot and press Enter…"
          />

          <PrioritiesSection
            value={form.source_priorities_default}
            onChange={(next) => setForm({ ...form, source_priorities_default: next })}
            hint={hintList("Built-in", resolved?.source_priorities_default)}
            disabled={!isAdmin}
          />

          <TrustRulesSection
            rows={form.trust_tier_rules}
            onChange={(next) => setForm({ ...form, trust_tier_rules: next })}
            disabled={!isAdmin}
          />

          <OverlayField
            label="Writer overlay"
            value={form.writer_overlay}
            onChange={(v) => setForm({ ...form, writer_overlay: v })}
            disabled={!isAdmin}
          />
          <OverlayField
            label="Planner overlay"
            value={form.planner_overlay}
            onChange={(v) => setForm({ ...form, planner_overlay: v })}
            disabled={!isAdmin}
          />
        </div>

        <footer className="sticky bottom-0 flex items-center justify-between gap-2 border-t border-argus-border-subtle bg-surface p-4">
          <div className="flex gap-2">
            {hasOverride && !isCreateFresh && isAdmin ? (
              <button
                type="button"
                onClick={() => setConfirmRetire(true)}
                disabled={busy}
                className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-3 py-1.5 text-[12px] font-medium text-argus-contested hover:bg-argus-contested hover:text-argus-inverse disabled:opacity-50"
              >
                Reset to default
              </button>
            ) : null}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-sm border border-argus-border-subtle bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:bg-elevated"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={busy || !isAdmin}
              className="rounded-sm border border-argus-accent-border bg-argus-accent px-3 py-1.5 text-[12px] font-medium text-argus-inverse hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Saving…" : isCreateFresh ? "Create mode" : hasOverride ? "Save changes" : "Save override"}
            </button>
          </div>
        </footer>

        {confirmRetire ? (
          <RetireConfirm
            modeName={name}
            onConfirm={onRetire}
            onCancel={() => setConfirmRetire(false)}
            busy={busy}
          />
        ) : null}
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function NameAndBase({
  isCreateFresh,
  nameLocked,
  name,
  setName,
  baseMode,
  setBaseMode,
  builtInNames,
}: {
  isCreateFresh: boolean;
  nameLocked: boolean;
  name: string;
  setName: (v: string) => void;
  baseMode: string | null;
  setBaseMode: (v: string | null) => void;
  builtInNames: string[];
}) {
  const nameId = useId();
  const baseId = useId();
  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div>
        <label htmlFor={nameId} className="argus-label">
          Mode slug
        </label>
        <input
          id={nameId}
          value={name}
          readOnly={nameLocked}
          onChange={(e) => setName(e.target.value)}
          className={`mt-1 w-full rounded-sm border px-2 py-1 font-mono text-[12px] ${
            nameLocked
              ? "border-argus-border-subtle bg-elevated text-argus-tertiary"
              : "border-argus-border-subtle bg-surface text-argus-primary"
          }`}
          placeholder={isCreateFresh ? "snake_case identifier" : ""}
          aria-readonly={nameLocked}
        />
        {nameLocked ? (
          <p className="mt-1 text-[10px] text-argus-tertiary">
            Slug locked after creation.
          </p>
        ) : null}
      </div>
      <div>
        <label htmlFor={baseId} className="argus-label">
          Base mode
        </label>
        <select
          id={baseId}
          value={baseMode ?? ""}
          disabled={!isCreateFresh}
          onChange={(e) => setBaseMode(e.target.value || null)}
          className="mt-1 w-full rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[12px] text-argus-primary disabled:bg-elevated disabled:text-argus-tertiary"
        >
          <option value="">None — fresh mode</option>
          {builtInNames.map((bn) => (
            <option key={bn} value={bn}>
              {bn}
            </option>
          ))}
        </select>
      </div>
    </section>
  );
}

function ScalarField({
  label,
  value,
  onChange,
  hint,
  disabled,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  disabled?: boolean;
  multiline?: boolean;
}) {
  const id = useId();
  return (
    <section>
      <label htmlFor={id} className="argus-label">
        {label}
      </label>
      {hint ? <p className="mb-1 text-[10px] text-argus-tertiary">{hint}</p> : null}
      {multiline ? (
        <textarea
          id={id}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          rows={2}
          className="w-full rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[12px] text-argus-primary disabled:bg-elevated"
        />
      ) : (
        <input
          id={id}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[12px] text-argus-primary disabled:bg-elevated"
        />
      )}
    </section>
  );
}

function ChipSection({
  label,
  chips,
  onChange,
  hint,
  disabled,
  placeholder,
}: {
  label: string;
  chips: string[];
  onChange: (next: string[]) => void;
  hint?: string;
  disabled?: boolean;
  placeholder?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const onCommit = () => {
    const v = draft.trim();
    if (!v) return;
    if (chips.includes(v)) {
      setDraft("");
      return;
    }
    onChange([...chips, v]);
    setDraft("");
  };
  return (
    <section>
      <label htmlFor={id} className="argus-label">
        {label}
      </label>
      {hint ? <p className="mb-1 text-[10px] text-argus-tertiary">{hint}</p> : null}
      <div className="flex flex-wrap gap-1.5 rounded-sm border border-argus-border-subtle bg-surface p-2">
        {chips.map((chip) => (
          <span
            key={chip}
            className="inline-flex items-center gap-1 rounded-sm border border-argus-border-subtle bg-elevated px-1.5 py-0.5 text-[11px] text-argus-primary"
          >
            <span className="font-mono">{chip}</span>
            {disabled ? null : (
              <button
                type="button"
                aria-label={`Remove ${chip}`}
                onClick={() => onChange(chips.filter((c) => c !== chip))}
                className="text-argus-tertiary hover:text-argus-contested"
              >
                ×
              </button>
            )}
          </span>
        ))}
        <input
          id={id}
          type="text"
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onCommit();
            }
          }}
          onBlur={onCommit}
          placeholder={placeholder}
          className="min-w-[120px] flex-1 bg-transparent text-[12px] text-argus-primary outline-none disabled:bg-elevated"
        />
      </div>
    </section>
  );
}

function PrioritiesSection({
  value,
  onChange,
  hint,
  disabled,
}: {
  value: SourceTypeLiteral[];
  onChange: (next: SourceTypeLiteral[]) => void;
  hint?: string;
  disabled?: boolean;
}) {
  const isOn = (s: SourceTypeLiteral) => value.includes(s);
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const copy = [...value];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  return (
    <section>
      <span className="argus-label">Source priorities (ordered)</span>
      {hint ? <p className="mb-1 text-[10px] text-argus-tertiary">{hint}</p> : null}
      <div className="rounded-sm border border-argus-border-subtle bg-surface p-2">
        <ol className="space-y-1" data-testid="priorities-ordered-list">
          {value.map((s, i) => (
            <li key={s} className="flex items-center justify-between gap-2 text-[12px]">
              <span className="font-mono text-argus-primary">
                {i + 1}. {s}
              </span>
              <span className="flex gap-1">
                <button
                  type="button"
                  aria-label={`Move ${s} up`}
                  onClick={() => move(i, -1)}
                  disabled={disabled || i === 0}
                  className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 text-[11px] text-argus-secondary hover:bg-elevated disabled:opacity-30"
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`Move ${s} down`}
                  onClick={() => move(i, +1)}
                  disabled={disabled || i === value.length - 1}
                  className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 text-[11px] text-argus-secondary hover:bg-elevated disabled:opacity-30"
                >
                  ↓
                </button>
                <button
                  type="button"
                  aria-label={`Remove ${s}`}
                  onClick={() => onChange(value.filter((x) => x !== s))}
                  disabled={disabled}
                  className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 text-[11px] text-argus-tertiary hover:text-argus-contested disabled:opacity-30"
                >
                  ×
                </button>
              </span>
            </li>
          ))}
        </ol>
        <div className="mt-2 flex flex-wrap gap-1">
          {ALLOWED_SOURCE_TYPES.filter((s) => !isOn(s)).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange([...value, s])}
              disabled={disabled}
              className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 py-0.5 font-mono text-[11px] text-argus-secondary hover:bg-elevated disabled:opacity-30"
            >
              + {s}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function TrustRulesSection({
  rows,
  onChange,
  disabled,
}: {
  rows: { source_type: SourceTypeLiteral; tier: TrustTierLiteral }[];
  onChange: (next: { source_type: SourceTypeLiteral; tier: TrustTierLiteral }[]) => void;
  disabled?: boolean;
}) {
  const used = new Set(rows.map((r) => r.source_type));
  const available = ALLOWED_SOURCE_TYPES.filter((s) => !used.has(s));
  const addRow = () => {
    if (available.length === 0) return;
    onChange([...rows, { source_type: available[0], tier: "credible_external" }]);
  };
  return (
    <section>
      <span className="argus-label">Trust tier rules</span>
      <p className="mb-1 text-[10px] text-argus-tertiary">
        Minimum trust tier accepted per source type. Empty = no override.
      </p>
      <div className="space-y-1.5 rounded-sm border border-argus-border-subtle bg-surface p-2">
        {rows.length === 0 ? (
          <p className="text-[11px] italic text-argus-tertiary">No rules — uses built-in defaults.</p>
        ) : null}
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2 text-[12px]">
            <select
              aria-label="Source type"
              value={r.source_type}
              disabled={disabled}
              onChange={(e) => {
                const copy = [...rows];
                copy[i] = { ...copy[i], source_type: e.target.value as SourceTypeLiteral };
                onChange(copy);
              }}
              className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 py-1 font-mono text-[11px] text-argus-primary"
            >
              {ALLOWED_SOURCE_TYPES.map((s) => (
                <option key={s} value={s} disabled={s !== r.source_type && used.has(s)}>
                  {s}
                </option>
              ))}
            </select>
            <span className="text-argus-tertiary">→</span>
            <select
              aria-label="Trust tier"
              value={r.tier}
              disabled={disabled}
              onChange={(e) => {
                const copy = [...rows];
                copy[i] = { ...copy[i], tier: e.target.value as TrustTierLiteral };
                onChange(copy);
              }}
              className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 py-1 text-[11px] text-argus-primary"
            >
              {ALLOWED_TRUST_TIERS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label={`Remove rule ${r.source_type}`}
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
              disabled={disabled}
              className="ml-auto rounded-sm border border-argus-border-subtle bg-surface px-1.5 py-0.5 text-[11px] text-argus-tertiary hover:text-argus-contested disabled:opacity-30"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addRow}
          disabled={disabled || available.length === 0}
          className="rounded-sm border border-argus-accent-border bg-argus-accent-bg px-2 py-0.5 text-[11px] font-medium text-argus-accent hover:bg-argus-accent hover:text-argus-inverse disabled:opacity-30"
        >
          + Add rule
        </button>
      </div>
    </section>
  );
}

function OverlayField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const over = value.length > OVERLAY_MAX;
  return (
    <section>
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="argus-label">
          {label}
        </label>
        <span
          className={`font-mono text-[10px] tabular-nums ${
            over ? "text-argus-contested" : "text-argus-tertiary"
          }`}
          data-testid={`${label.replace(/\s+/g, "-").toLowerCase()}-counter`}
        >
          {value.length} / {OVERLAY_MAX}
        </span>
      </div>
      <textarea
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        aria-invalid={over ? true : undefined}
        className={`w-full rounded-sm border px-2 py-1 text-[12px] text-argus-primary disabled:bg-elevated ${
          over ? "border-argus-contested" : "border-argus-border-subtle bg-surface"
        }`}
      />
    </section>
  );
}

function RetireConfirm({
  modeName,
  onConfirm,
  onCancel,
  busy,
}: {
  modeName: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div role="alertdialog" aria-label="Confirm retire" className="absolute inset-0 z-10 flex items-center justify-center bg-black/30">
      <div className="w-[360px] rounded-argus-md border border-argus-border-moderate bg-surface p-4 shadow-xl">
        <h3 className="font-serif text-[15px] font-semibold text-argus-primary">
          Reset {modeName} to built-in default?
        </h3>
        <p className="mt-2 text-[12px] text-argus-secondary">
          The firm override will be retired. Engagements will start using the
          built-in mode again. You can restore the override later if you
          change your mind.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-sm border border-argus-border-subtle bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:bg-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-sm border border-argus-contested-border bg-argus-contested px-3 py-1.5 text-[12px] font-medium text-argus-inverse hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Retiring…" : "Reset to built-in"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hintIfDefault(builtInValue?: string, overrideValue?: string): string | undefined {
  if (overrideValue !== undefined) return undefined;
  if (!builtInValue) return undefined;
  return `Built-in default: "${truncate(builtInValue, 80)}"`;
}

function hintList(prefix: string, list?: string[]): string | undefined {
  if (!list || list.length === 0) return undefined;
  return `${prefix}: ${list.join(", ")}`;
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
