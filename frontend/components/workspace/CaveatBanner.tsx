"use client";

import { useState } from "react";

import type { ClaimSupportRow, StructuredAnswer } from "@/lib/types";

export interface CaveatFailure {
  claimId: string | null;
  text: string;
  kind: "unsupported" | "weak";
  chunkRefs: string[];
}

/**
 * Pull NLI failures from either the structured_answer (per-(claim, chunk) NLI)
 * or claim_support (per-claim NLI verdict).
 *
 * structured_answer is the streamed source of truth; claim_support is the
 * post-pipeline mirror. We dedupe by (text, kind).
 */
export function collectFailures(
  structured: StructuredAnswer | null | undefined,
  claimSupport: ClaimSupportRow[],
): CaveatFailure[] {
  const out: CaveatFailure[] = [];
  const seen = new Set<string>();

  // Streaming source: structured_answer
  if (structured?.sections) {
    for (const section of structured.sections) {
      for (const claim of section.claims ?? []) {
        const labels = (claim.nli_results ?? []).map((r) => r.label);
        if (labels.length === 0) continue;
        const hasContradiction = labels.includes("contradiction");
        const allNeutral = labels.every((l) => l === "neutral" || l === "skipped");
        const kind: "unsupported" | "weak" | null = hasContradiction
          ? "unsupported"
          : allNeutral
            ? "weak"
            : null;
        if (!kind) continue;
        const key = `${kind}:${claim.text}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({
          claimId: null,
          text: claim.text,
          kind,
          chunkRefs: claim.chunk_ids ?? [],
        });
      }
    }
  }

  // Post-pipeline source: claim_support rows
  for (const row of claimSupport) {
    const verdict = String(row.verifier_verdict || "").toLowerCase();
    const label = String(row.nli_label || "").toLowerCase();
    const kind: "unsupported" | "weak" | null =
      verdict === "unsupported" || verdict === "overstates" || row.contradiction_flag || label === "contradiction"
        ? "unsupported"
        : row.weak_or_unsupported || verdict === "weak" || label === "neutral"
          ? "weak"
          : null;
    if (!kind || !row.claim_text) continue;
    const key = `${kind}:${row.claim_text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      claimId: row.claim_id ?? null,
      text: row.claim_text,
      kind,
      chunkRefs: row.evidence_object_ids ?? [],
    });
  }

  return out;
}

/**
 * CaveatBanner — surfaces NLI verification failures (contradicted + weak claims).
 * Sits at the top of an answer with an oxblood left border. Expandable list,
 * each item links to the claim via onReview(claimId).
 */
export default function CaveatBanner({
  failures,
  onReview,
  verifying = false,
}: {
  failures: CaveatFailure[];
  onReview?: (claimId: string | null) => void;
  verifying?: boolean;
}) {
  const [open, setOpen] = useState(false);

  if (failures.length === 0 && !verifying) return null;

  const unsupportedCount = failures.filter((f) => f.kind === "unsupported").length;
  const weakCount = failures.filter((f) => f.kind === "weak").length;

  return (
    <aside
      className="border border-argus-border-subtle bg-surface"
      style={{ borderLeft: "3px solid var(--text-oxblood)" }}
      role="region"
      aria-label="Verification caveats"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-elevated"
      >
        <span className="flex items-center gap-2">
          <span className="argus-label" style={{ color: "var(--text-oxblood)" }}>
            Verification caveats
          </span>
          {failures.length > 0 ? (
            <span className="font-mono text-[10px] tabular-nums text-argus-tertiary">
              {unsupportedCount > 0 ? `${unsupportedCount} contradicted` : null}
              {unsupportedCount > 0 && weakCount > 0 ? " · " : null}
              {weakCount > 0 ? `${weakCount} weak` : null}
            </span>
          ) : null}
          {verifying ? (
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-argus-tertiary">
              <span className="argus-cite-spinner" aria-hidden style={{ color: "var(--text-oxblood)" }} />
              Verifying claims…
            </span>
          ) : null}
        </span>
        {failures.length > 0 ? (
          <span className="text-[10px] text-argus-tertiary">{open ? "Hide" : "Review"}</span>
        ) : null}
      </button>

      {open && failures.length > 0 ? (
        <ul className="border-t border-argus-border-subtle px-4 py-2.5 text-[12px]">
          {failures.map((f, i) => (
            <li key={i} className="flex items-start gap-2 py-1.5">
              <span
                className="mt-0.5 inline-block rounded-sm border px-1 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider"
                style={
                  f.kind === "unsupported"
                    ? {
                        color: "var(--trust-contested)",
                        background: "var(--trust-contested-bg)",
                        borderColor: "var(--trust-contested-border)",
                      }
                    : {
                        color: "var(--trust-web)",
                        background: "var(--trust-web-bg)",
                        borderColor: "var(--trust-web-border)",
                      }
                }
              >
                {f.kind === "unsupported" ? "Contradicted" : "Weak"}
              </span>
              <p className="min-w-0 flex-1 font-serif leading-snug text-argus-secondary">
                {f.text}
              </p>
              {onReview ? (
                <button
                  type="button"
                  onClick={() => onReview(f.claimId)}
                  className="shrink-0 font-medium text-argus-accent hover:underline"
                >
                  Review →
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </aside>
  );
}
