"use client";

import { formatVerdict } from "@/lib/formatters";
import { useClaimHighlight, useSelection } from "@/lib/SelectionContext";
import type { ClaimSupportRow } from "@/lib/types";

export default function ClaimChip({
  claimId,
  rows,
  onClick,
}: {
  claimId: string;
  rows: ClaimSupportRow[];
  onClick?: (claimId: string) => void;
}) {
  const row = rows.find((r) => r.claim_id === claimId);
  const verdict = formatVerdict(row?.verifier_verdict ?? null);
  const known = !!row;
  const { isActive, isSelected } = useClaimHighlight(claimId);
  const { setHoveredClaim, setSelectedClaim } = useSelection();

  const handleClick = () => {
    if (onClick) onClick(claimId);
    else setSelectedClaim(claimId);
  };

  return (
    <button
      type="button"
      data-claim-id={claimId}
      onClick={handleClick}
      onMouseEnter={() => setHoveredClaim(claimId)}
      onMouseLeave={() => setHoveredClaim(null)}
      className={`ml-1 inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 align-middle text-[10px] font-medium leading-none transition-all ${
        isSelected ? "scale-105 shadow-argus-sm" : ""
      } ${isActive ? "ring-1 ring-argus-accent/60" : ""} hover:opacity-80`}
      style={{
        backgroundColor: known ? `${verdict.color}1c` : "transparent",
        color: known ? verdict.color : "var(--text-tertiary)",
        borderColor: known ? `${verdict.color}55` : "var(--border-subtle)",
      }}
      title={
        known
          ? `${claimId} · ${verdict.label} · click to open evidence`
          : `${claimId} · click to open evidence`
      }
      aria-label={`Open evidence for claim ${claimId}`}
      aria-pressed={isSelected}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: known ? verdict.color : "var(--text-tertiary)" }}
        aria-hidden
      />
      {claimId}
    </button>
  );
}
