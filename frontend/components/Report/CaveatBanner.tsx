"use client";

import type { ClaimSupportRow, Report } from "@/lib/types";

function WarnIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
    </svg>
  );
}

export default function CaveatBanner({
  report,
  rows,
}: {
  report: Report;
  rows: ClaimSupportRow[];
}) {
  const unsupportedFromCount = report.unsupported_claim_count ?? 0;
  const weakOrUnsupportedCount = rows.filter((r) => {
    const v = String(r.verifier_verdict || "").toLowerCase();
    return (
      r.weak_or_unsupported ||
      v === "weak" ||
      v === "unsupported" ||
      v === "overstates" ||
      r.contradiction_flag
    );
  }).length;

  const total = rows.length;
  const flagged = Math.max(unsupportedFromCount, weakOrUnsupportedCount);

  if (flagged === 0) return null;

  // Tone: severe (any unsupported/overstates) vs cautionary (only weak/inference).
  const severe = rows.some((r) => {
    const v = String(r.verifier_verdict || "").toLowerCase();
    return v === "unsupported" || v === "overstates" || r.contradiction_flag;
  });

  const tone = severe
    ? {
        wrap: "border-argus-danger-border bg-argus-danger-subtle",
        icon: "text-argus-danger",
        label: "text-argus-danger",
        body: "text-argus-secondary",
      }
    : {
        wrap: "border-argus-warning-border bg-argus-warning-subtle/60",
        icon: "text-argus-warning",
        label: "text-argus-warning",
        body: "text-argus-secondary",
      };

  return (
    <div
      role="alert"
      className={`mb-6 flex items-start gap-3 rounded-argus-md border ${tone.wrap} px-4 py-3`}
    >
      <WarnIcon className={`mt-0.5 h-4 w-4 shrink-0 ${tone.icon}`} />
      <div className="min-w-0 flex-1 text-[13px]">
        <p className={`font-semibold ${tone.label}`}>
          {flagged} of {total} claim{total === 1 ? "" : "s"} flagged by the verifier — review before
          client delivery.
        </p>
        <p className={`mt-1 ${tone.body}`}>
          {severe ? (
            <>
              At least one claim is unsupported or overstates its evidence. Cross-check the audit
              panel and the verifier report below before sharing this deliverable.
            </>
          ) : (
            <>
              All flagged claims are weakly supported (inference-only or partial coverage). The
              recommendation does not rest solely on these claims, but a careful reader should know.
            </>
          )}
        </p>
      </div>
    </div>
  );
}
