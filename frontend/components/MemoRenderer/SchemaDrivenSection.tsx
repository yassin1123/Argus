"use client";

/**
 * Phase 2 / Week 7 / Day 3 — generic schema-driven section renderer.
 *
 * Walks an unknown JSON shape and renders by type:
 *   string                → paragraph
 *   number / boolean      → inline value
 *   list[string]          → bullet list
 *   list[dict]            → table (column headers = union of keys)
 *   list of mixed scalars → bullet list
 *   dict                  → labeled subsection (recurses)
 *
 * The "always produces something readable" guarantee per spec:
 * unknown shapes fall through to a labeled JSON dump-styled block —
 * but rendered as readable monospace, not raw JSON dump (per hard
 * rule "Don't fall back to raw JSON dump").
 *
 * Naming: this lives under MemoRenderer/, not MemoEditor/, because
 * `frontend/components/workspace/MemoEditor.tsx` is already taken
 * (it's the Tiptap-based artifact text editor — different concern).
 */

import { Fragment } from "react";

import ClaimCommentAffordance from "../Comments/ClaimCommentAffordance";
import ClaimVerificationFeedback from "../PilotFeedback/ClaimVerificationFeedback";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [k: string]: JsonValue };

export interface SchemaDrivenSectionProps {
  /** Section heading. Optional — when omitted, renders inline. */
  title?: string;
  /** Any JSON-shaped value. Renderer chooses display by type. */
  value: JsonValue;
  /** Internal: nesting depth, used for heading levels. */
  depth?: number;
}

const HEADING_CLASSES = [
  "font-serif text-[18px] font-semibold text-argus-primary",
  "font-serif text-[15px] font-semibold text-argus-primary",
  "font-serif text-[13px] font-semibold uppercase tracking-wide text-argus-secondary",
  "font-mono text-[11px] uppercase tracking-wide text-argus-tertiary",
];

function headingClassFor(depth: number): string {
  return HEADING_CLASSES[Math.min(depth, HEADING_CLASSES.length - 1)];
}

function humanizeKey(k: string): string {
  return k
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isPlainObject(v: JsonValue): v is { [k: string]: JsonValue } {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function isAllStrings(arr: JsonValue[]): arr is string[] {
  return arr.every((x) => typeof x === "string");
}

function isAllScalars(arr: JsonValue[]): boolean {
  return arr.every(
    (x) => x === null || ["string", "number", "boolean"].includes(typeof x),
  );
}

function isAllObjects(arr: JsonValue[]): arr is { [k: string]: JsonValue }[] {
  return arr.every(isPlainObject);
}

function unionKeys(rows: { [k: string]: JsonValue }[]): string[] {
  const seen: Record<string, true> = {};
  const out: string[] = [];
  for (const r of rows) {
    for (const k of Object.keys(r)) {
      if (!seen[k]) {
        seen[k] = true;
        out.push(k);
      }
    }
  }
  return out;
}

function scalarDisplay(v: JsonValue): string {
  if (v === null) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
}

export default function SchemaDrivenSection({
  title,
  value,
  depth = 0,
}: SchemaDrivenSectionProps) {
  return (
    <section className="mb-4" data-testid={title ? `section-${title}` : undefined}>
      {title ? (
        <h3 className={`${headingClassFor(depth)} mb-2`}>{humanizeKey(title)}</h3>
      ) : null}
      <SchemaValue value={value} depth={depth + 1} />
    </section>
  );
}

function SchemaValue({ value, depth }: { value: JsonValue; depth: number }) {
  // Scalars + null
  if (value === null || value === undefined) {
    return <span className="text-argus-tertiary">—</span>;
  }
  if (typeof value === "string") {
    if (!value.trim()) return <span className="text-argus-tertiary">—</span>;
    return <p className="text-[13px] leading-relaxed text-argus-primary">{value}</p>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <span className="font-mono text-[12px] tabular-nums text-argus-primary">
        {scalarDisplay(value)}
      </span>
    );
  }

  // Arrays
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-argus-tertiary">—</span>;
    }
    if (isAllStrings(value)) {
      return (
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-argus-primary">
          {value.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      );
    }
    if (isAllObjects(value)) {
      const cols = unionKeys(value);
      return (
        <div className="overflow-x-auto rounded-argus-sm border border-argus-border-subtle">
          <table className="w-full text-[12px]" data-testid="schema-driven-table">
            <thead className="bg-elevated">
              <tr>
                {cols.map((c) => (
                  <th
                    key={c}
                    className="border-b border-argus-border-subtle px-2 py-1 text-left font-medium uppercase tracking-wide text-argus-tertiary"
                  >
                    {humanizeKey(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((row, i) => (
                <tr key={i} className="border-b border-argus-border-subtle last:border-0">
                  {cols.map((c) => {
                    // W16/D3: claim_id columns get an inline
                    // "Comment on this claim" affordance next to the
                    // value so the reader can drop a thread without
                    // leaving the row.
                    const isClaimColumn = c === "claim_id" || c === "claim_ids";
                    const cellValue = row[c] ?? null;
                    return (
                      <td key={c} className="px-2 py-1 align-top text-argus-primary">
                        <SchemaValue value={cellValue} depth={depth + 1} />
                        {isClaimColumn && typeof cellValue === "string" && cellValue ? (
                          <span className="ml-1">
                            <ClaimCommentAffordance claimId={cellValue} compact />
                            <ClaimVerificationFeedback claimId={cellValue} compact />
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    if (isAllScalars(value)) {
      return (
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-argus-primary">
          {value.map((s, i) => (
            <li key={i}>{scalarDisplay(s)}</li>
          ))}
        </ul>
      );
    }
    // Mixed shape — render each item as its own subsection.
    return (
      <ol className="space-y-3">
        {value.map((item, i) => (
          <li key={i} className="rounded-sm border border-argus-border-subtle bg-surface p-2">
            <SchemaValue value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }

  // Plain object — recurse with each key as a labeled subsection.
  if (isPlainObject(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return <span className="text-argus-tertiary">—</span>;
    }
    return (
      <div className="space-y-3">
        {entries.map(([k, v]) => (
          <Fragment key={k}>
            <SchemaDrivenSection title={k} value={v} depth={depth} />
          </Fragment>
        ))}
      </div>
    );
  }

  // Final safety net: render as readable inline text. Never raw JSON dump.
  return (
    <span className="font-mono text-[11px] text-argus-tertiary">
      {String(value)}
    </span>
  );
}
