import Link from "next/link";
import type { Session } from "@/lib/types";
import { relativeTime } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";

function statusVariant(
  status: Session["status"]
): "neutral" | "info" | "success" | "danger" | "warning" {
  switch (status) {
    case "complete":
      return "success";
    case "processing":
    case "pending":
      return "info";
    case "failed":
      return "danger";
    case "insufficient":
      return "warning";
    default:
      return "neutral";
  }
}

function formatMode(mode?: string): string {
  if (!mode) return "";
  return mode
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function SessionCard({ s }: { s: Session }) {
  const v = statusVariant(s.status);
  return (
    <Link
      href={`/sessions/${s.id}`}
      className="group block rounded-[16px] border border-argus-border-subtle bg-surface p-5 shadow-argus-sm transition-all duration-150 hover:border-argus-border-moderate hover:shadow-argus"
    >
      <div className="mb-2 flex items-start justify-between gap-4">
        <Badge variant={v}>{s.status}</Badge>
        <span className="mt-0.5 shrink-0 text-[11px] text-argus-tertiary">
          {relativeTime(s.created_at)}
        </span>
      </div>
      <p className="truncate font-semibold text-argus-primary transition-colors duration-150 group-hover:text-argus-accent">
        {s.title}
      </p>
      <p className="mt-1.5 line-clamp-2 text-sm leading-[1.5] text-argus-secondary">{s.query}</p>
      {s.status === "complete" && s.recommendation_preview ? (
        <p className="mt-3 line-clamp-2 rounded-[10px] border border-argus-border-subtle bg-argus-neutral-subtle/60 px-3 py-2 text-[13px] leading-snug text-argus-primary">
          {s.recommendation_preview}
        </p>
      ) : null}
      {s.status === "complete" && s.report_mode && (
        <div className="mt-3 flex items-center gap-2">
          <span className="rounded-full border border-argus-border-subtle bg-argus-neutral-subtle px-2 py-0.5 text-[10px] font-semibold text-argus-neutral">
            {formatMode(s.report_mode)}
          </span>
          {s.evidence_count != null && s.evidence_count > 0 && (
            <span className="text-[11px] text-argus-tertiary">{s.evidence_count} sources</span>
          )}
        </div>
      )}
    </Link>
  );
}
