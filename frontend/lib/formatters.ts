import type { EvidenceBundleItem } from "@/lib/types";

/** User-facing source label — never a raw UUID. */
export function formatSourceLabel(item: Partial<EvidenceBundleItem> | Record<string, unknown>): string {
  const title = String((item as EvidenceBundleItem).title || "").trim();
  if (title) return title.slice(0, 200);
  const url = String(
    (item as EvidenceBundleItem).source_url || (item as EvidenceBundleItem).url || ""
  ).trim();
  if (url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return url.slice(0, 60);
    }
  }
  const fn = String((item as EvidenceBundleItem).filename || "").trim();
  if (fn) return fn.slice(0, 120);
  return "Source";
}

export function formatVerdict(verdict: string | null | undefined): {
  label: string;
  color: string;
} {
  const v = (verdict || "").toLowerCase();
  const map: Record<string, { label: string; color: string }> = {
    supported: { label: "Verified", color: "#1A6B3C" },
    supports: { label: "Verified", color: "#1A6B3C" },
    weak: { label: "Partial", color: "#C05C00" },
    unsupported: { label: "Unverified", color: "#B91C1C" },
    overstates: { label: "Overstated", color: "#C05C00" },
    contradicts: { label: "Contested", color: "#B91C1C" },
  };
  return map[v] ?? { label: "Unknown", color: "#5A6070" };
}

export function formatPipelineStage(event: string | null | undefined): string {
  const e = String(event || "").trim();
  const map: Record<string, string> = {
    pipeline_start: "Starting analysis",
    plan_ready: "Research plan created",
    research_gathered: "Evidence gathered",
    analysis_v1_done: "First analysis complete",
    critique_done: "Stress test complete",
    analysis_v2_done: "Analysis revised",
    gates_validated: "Evidence validated",
    critic_post_done: "Second stress test complete",
    verification_done: "Claims verified",
    deliverable_ready: "Report ready",
    failed: "Stopped with error",
  };
  return map[e] || e.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Map similarity 0–1 to 1–4 filled dots for display. */
export function similarityStrengthDots(sim: number | undefined): { filled: number; label: string } {
  if (sim == null || Number.isNaN(sim)) return { filled: 0, label: "" };
  if (sim >= 0.45) return { filled: 4, label: "High" };
  if (sim >= 0.28) return { filled: 3, label: "Medium" };
  if (sim >= 0.15) return { filled: 2, label: "Low" };
  return { filled: 1, label: "Low" };
}

/** Remove UUIDs and clumsy evidence-ID phrases from user-visible strings. */
export function sanitizeUserFacingText(text: string): string {
  let t = text;
  t = t.replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "");
  t = t.replace(/Supported by evidence ID\s*/gi, "");
  t = t.replace(/\s{2,}/g, " ").trim();
  return t;
}
