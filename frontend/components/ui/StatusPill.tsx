import type { ArtifactStatus } from "@/lib/types";

/**
 * Small status pill used by both engagements (draft/processing/complete/failed/insufficient)
 * and artifacts (draft/review/final). Same visual language across the app — adopt this
 * instead of one-off colored spans.
 */

export type EngagementStatus =
  | "draft"
  | "pending"
  | "processing"
  | "complete"
  | "failed"
  | "insufficient";

type AnyStatus = EngagementStatus | ArtifactStatus;

const TONE: Record<AnyStatus, string> = {
  // Engagement
  draft: "border-argus-border-subtle bg-elevated text-argus-tertiary",
  pending: "border-argus-web-border bg-argus-web-bg text-argus-web",
  processing: "border-argus-credible-border bg-argus-credible-bg text-argus-credible",
  complete: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  failed: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
  insufficient: "border-argus-web-border bg-argus-web-bg text-argus-web",
  // Artifact
  review: "border-argus-web-border bg-argus-web-bg text-argus-web",
  final: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
};

const LABEL: Record<AnyStatus, string> = {
  draft: "Draft",
  pending: "Pending",
  processing: "Processing",
  complete: "Complete",
  failed: "Failed",
  insufficient: "Insufficient",
  review: "Review",
  final: "Final",
};

export default function StatusPill({
  status,
  pulse,
  className = "",
}: {
  status: AnyStatus;
  /** Pulse the dot (use for in-flight states like processing). */
  pulse?: boolean;
  className?: string;
}) {
  const dotPulse = pulse ?? (status === "processing" || status === "pending");
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${TONE[status]} ${className}`}
    >
      <span
        aria-hidden
        className={`inline-block h-1.5 w-1.5 rounded-full bg-current ${dotPulse ? "animate-pulse" : ""}`}
      />
      {LABEL[status]}
    </span>
  );
}
