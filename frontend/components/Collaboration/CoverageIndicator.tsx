"use client";

import { CoverageMap, STATUS_COLOR, STATUS_LABEL } from "@/lib/api/collaboration";

interface Props {
  coverage: CoverageMap | null;
  /** When the viewing user is the lead, the unassigned sections get
   *  highlighted (red dot) instead of muted (grey). */
  isLead?: boolean;
  compact?: boolean;
}

/**
 * Section coverage rollup — "6 of 8 sections assigned · 3 done · 2 in
 * progress · 1 needs review · 2 unassigned · ready_to_submit".
 *
 * Lives in the WorkspaceTopBar so the lead sees coverage at a glance
 * without having to scroll through the memo. The ``ready_to_submit``
 * flag is purely advisory (W17/D2 hard rule — no auto-submit) and
 * renders next to the rollup as a single icon.
 */
export default function CoverageIndicator({
  coverage,
  isLead = false,
  compact = false,
}: Props) {
  if (!coverage) {
    return (
      <span
        data-testid="coverage-indicator"
        style={{ fontSize: 11, color: "#6b7280" }}
      >
        Loading coverage…
      </span>
    );
  }

  const total = coverage.entries.length;
  const assigned = total - coverage.unassigned_count;
  const statuses: Array<keyof typeof STATUS_LABEL> = [
    "done", "in_progress", "needs_review", "not_started",
  ];

  return (
    <span
      data-testid="coverage-indicator"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontSize: 11,
        color: "#4b5563",
      }}
    >
      <span data-testid="coverage-summary">
        <strong>{assigned}</strong> of <strong>{total}</strong> assigned
      </span>
      {!compact && (
        <span style={{ display: "inline-flex", gap: 4 }}>
          {statuses.map((s) => {
            const n = coverage.by_status[s] ?? 0;
            if (n === 0) return null;
            const c = STATUS_COLOR[s];
            return (
              <span
                key={s}
                data-testid={`coverage-status-${s}`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 2,
                  padding: "0 4px",
                  background: c.bg,
                  border: `1px solid ${c.border}`,
                  borderRadius: 3,
                  color: c.fg,
                }}
              >
                <strong>{n}</strong> {STATUS_LABEL[s].toLowerCase()}
              </span>
            );
          })}
        </span>
      )}
      {coverage.unassigned_count > 0 && (
        <span
          data-testid="coverage-unassigned-count"
          style={{
            padding: "0 4px",
            borderRadius: 3,
            background: isLead ? "#fee2e2" : "#f3f4f6",
            color: isLead ? "#991b1b" : "#6b7280",
            border: `1px solid ${isLead ? "#fecaca" : "#e5e7eb"}`,
            fontWeight: isLead ? 700 : 400,
          }}
        >
          {coverage.unassigned_count} unassigned
        </span>
      )}
      {coverage.ready_to_submit && (
        <span
          data-testid="coverage-ready-to-submit"
          title="All sections complete — advisory only; partners decide when to submit"
          style={{
            padding: "0 6px",
            background: "#dcfce7",
            border: "1px solid #86efac",
            borderRadius: 3,
            color: "#166534",
            fontWeight: 700,
          }}
        >
          ✓ ready to submit
        </span>
      )}
    </span>
  );
}
