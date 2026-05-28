// API client for /api/admin/observability/dashboard — Phase 5 / Week 20 / Day 5.
// Backend at backend/api/observability_dashboard.py is the source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export interface VolumeBlock {
  started: number;
  completed: number;
  failed: number;
  in_flight: number;
  success_rate_pct: number;
  by_mode: Record<string, { count: number }>;
}

export interface VerificationBlock {
  verdicts: Record<string, number>;
  total: number;
  supported_pct: number;
  partial_pct: number;
  insufficient_pct: number;
}

export interface CostModelRow {
  model?: string;
  label?: string;
  provider?: string;
  call_count?: number;
  count?: number;
  total_usd?: number;
  cost_usd?: number;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface CostBlock {
  scope: "firm" | "system";
  firm_id: string | null;
  total_usd: number;
  call_count?: number;
  engagement_count?: number;
  by_model: CostModelRow[];
}

export interface DashboardFailureRow {
  session_id: string;
  firm_id: string | null;
  status: string | null;
  pipeline_state: string | null;
  report_mode: string | null;
  started_at: string | null;
  updated_at: string | null;
  total_cost_usd: number;
  failed_stage: string | null;
  error_message: string | null;
}

export interface VerificationQualityBlock {
  measured: boolean;
  fp_rate_on_supported: number | null;
  recall_on_insufficient: number | null;
  accuracy: number | null;
  red_team_catch_rate: number | null;
  red_team_escapes: number | null;
  verifier_source: string | null;
  as_of: string | null;
}

export interface DashboardData {
  hours: number;
  from: string;
  to: string;
  firm_scoped_to: string | null;
  volume: VolumeBlock;
  artifacts_generated: number;
  verification: VerificationBlock;
  verification_quality?: VerificationQualityBlock;
  cost: CostBlock;
  // W24/D3: firm-scoped pilot-health aggregate (null for system-wide).
  pilot_health?: import("./pilotFeedback").PilotHealth | null;
  recent_failures: DashboardFailureRow[];
}

export async function getDashboard(
  opts: { hours?: number; firmId?: string } = {},
): Promise<DashboardData> {
  const params = new URLSearchParams();
  if (opts.hours) params.set("hours", String(opts.hours));
  if (opts.firmId) params.set("firm_id", opts.firmId);
  const qs = params.toString();
  const res = await fetch(
    `${BASE_URL}/api/admin/observability/dashboard${qs ? `?${qs}` : ""}`,
    { credentials: FETCH_CREDS },
  );
  if (!res.ok) {
    throw new Error(`getDashboard failed: ${res.status}`);
  }
  return res.json();
}
