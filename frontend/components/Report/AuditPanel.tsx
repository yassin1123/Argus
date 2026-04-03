"use client";

import { useState } from "react";
import type { ClaimSupportRow } from "@/lib/types";
import { AnimatedExpand } from "@/components/ui/AnimatedExpand";

function TerminalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 17l6-6-6-6M12 19h8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function verificationSummary(verification: unknown): string | null {
  if (!verification || typeof verification !== "object") return null;
  const v = verification as Record<string, unknown>;
  const overall = String(v.overall || "").trim();
  const gap = String(v.gap_summary || "").trim();
  const assessments = v.claim_assessments;
  const n = Array.isArray(assessments) ? assessments.length : 0;
  const parts: string[] = [];
  if (overall) parts.push(overall);
  if (gap) parts.push(gap);
  if (n) parts.push(`${n} claim assessments recorded.`);
  return parts.length ? parts.join(" ") : null;
}

function reasoningGraphSummary(reasoningGraph: unknown): string | null {
  if (!reasoningGraph || typeof reasoningGraph !== "object") return null;
  const g = reasoningGraph as Record<string, unknown>;
  const nodes = g.nodes;
  const edges = g.edges;
  const nn = Array.isArray(nodes) ? nodes.length : 0;
  const ne = Array.isArray(edges) ? edges.length : 0;
  if (!nn && !ne) return null;
  return `Reasoning map: ${nn} nodes, ${ne} links.`;
}

export function AuditPanel({
  verification,
  reasoningGraph,
  claimSupport,
}: {
  verification: unknown;
  reasoningGraph: unknown;
  claimSupport: ClaimSupportRow[];
}) {
  const [open, setOpen] = useState(false);
  const vSum = verificationSummary(verification);
  const gSum = reasoningGraphSummary(reasoningGraph);
  const hasSomething = Boolean(vSum || gSum || claimSupport.length > 0);

  if (!hasSomething) return null;

  return (
    <div className="mt-16 border-t border-argus-border-subtle pt-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-argus-tertiary transition-colors duration-150 hover:text-argus-secondary"
        aria-expanded={open}
      >
        <TerminalIcon />
        Advanced audit
        <Chevron open={open} />
      </button>
      <AnimatedExpand show={open}>
        <div className="mt-4 space-y-3 rounded-[12px] border border-argus-border-subtle bg-canvas/50 p-4 text-sm text-argus-secondary">
          {vSum ? (
            <p>
              <span className="font-semibold text-argus-primary">Verification: </span>
              {vSum}
            </p>
          ) : null}
          {gSum ? (
            <p>
              <span className="font-semibold text-argus-primary">Structure: </span>
              {gSum}
            </p>
          ) : null}
          {claimSupport.length > 0 ? (
            <p className="text-argus-tertiary">
              Claim-level detail is in <strong className="text-argus-secondary">Claim analysis</strong> above.
            </p>
          ) : null}
        </div>
      </AnimatedExpand>
    </div>
  );
}
