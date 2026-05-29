// API client for the W25/D2 live-pilot watch view.
// GET /api/admin/observability/live-pilot — short-poll friendly.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export interface LiveEngagement {
  session_id: string;
  title: string;
  status: string;
  pipeline_state: string | null;
  report_mode: string | null;
  updated_at: string | null;
  cost_usd: number;
  active: boolean;
}

export interface PilotAlert {
  kind: string;
  severity: "warn" | "critical";
  firm_id: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface LivePilotView {
  firm_id: string;
  generated_at: string;
  window_minutes: number;
  active_engagements: LiveEngagement[];
  verification_distribution: {
    total: number;
    supported_pct: number;
    partial_pct: number;
    insufficient_pct: number;
    verdicts: Record<string, number>;
  };
  cost_burn: {
    month_to_date_usd: number;
    today_usd: number;
    monthly_budget_usd: number | null;
    used_pct: number | null;
    blocks_new_engagements: boolean;
  };
  feedback: {
    recent_claim_feedback: { assessment: string; at: string | null }[];
    recent_artifact_ratings: { rating: number; artifact_type: string | null; at: string | null }[];
  };
  alerts: PilotAlert[];
  alert_count: number;
  has_critical: boolean;
}

export async function getLivePilot(opts: { firmId?: string; windowMinutes?: number } = {}): Promise<LivePilotView> {
  const qs = new URLSearchParams();
  if (opts.firmId) qs.set("firm_id", opts.firmId);
  if (opts.windowMinutes) qs.set("window_minutes", String(opts.windowMinutes));
  const q = qs.toString();
  const res = await fetch(
    `${BASE_URL}/api/admin/observability/live-pilot${q ? `?${q}` : ""}`,
    { credentials: FETCH_CREDS, cache: "no-store" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json() as Promise<LivePilotView>;
}
