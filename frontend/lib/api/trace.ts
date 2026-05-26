// API client for /api/sessions/{id}/trace + /api/admin/traces/recent
// — Phase 5 / Week 20 / Day 4. Mirrors backend/core/observability/trace_view.py
// shapes; never carries claim/evidence/memo prose by contract.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export interface TimelineStage {
  stage: string;
  at: string | null;
  duration_ms: number | null;
  detail: string | null;
  ok: boolean;
}

export interface StageRollup {
  agent: string;
  call_count: number;
  cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  error_count: number;
}

export interface LLMCallRow {
  agent: string;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number;
  success: boolean;
  error_kind: string | null;
  at: string | null;
}

export interface VerificationSummary {
  assessments_total: number;
  verdict_distribution: Record<string, number>;
}

export interface RetrievalSummary {
  evidence_count: number;
  evidence_by_source: Record<string, number>;
  followup_query_count: number;
}

export interface FailureRecord {
  failed: boolean;
  failed_stage: string | null;
  last_successful_stage: string | null;
  error_message: string | null;
  error_kind: string | null;
  writer_schema_failure: { schema_name?: string; field_path?: string } | null;
}

export interface EngagementTrace {
  session_id: string;
  firm_id: string | null;
  run_id: string | null;
  status: string | null;
  pipeline_state: string | null;
  report_mode: string | null;
  started_at: string | null;
  ended_at: string | null;
  wall_ms: number | null;
  total_cost_usd: number;
  timeline: TimelineStage[];
  stage_rollups: StageRollup[];
  llm_calls: LLMCallRow[];
  verification: VerificationSummary;
  retrieval: RetrievalSummary;
  versions: Array<{
    version_number: number;
    change_type: string;
    change_summary: string | null;
    review_state: string | null;
    created_at: string | null;
    created_by: string | null;
  }>;
  failure: FailureRecord;
  gaps: string[];
}

export interface RecentTraceRow {
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

export async function getEngagementTrace(
  sessionId: string,
  opts: { runId?: string } = {},
): Promise<EngagementTrace> {
  const qs = opts.runId ? `?run_id=${encodeURIComponent(opts.runId)}` : "";
  const res = await fetch(
    `${BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/trace${qs}`,
    { credentials: FETCH_CREDS },
  );
  if (!res.ok) {
    throw new Error(`getEngagementTrace failed: ${res.status}`);
  }
  return res.json();
}

export async function getRecentTraces(
  opts: { status?: string; hours?: number; firmId?: string } = {},
): Promise<{ traces: RecentTraceRow[]; status_filter: string | null }> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.hours) params.set("hours", String(opts.hours));
  if (opts.firmId) params.set("firm_id", opts.firmId);
  const qs = params.toString();
  const res = await fetch(
    `${BASE_URL}/api/admin/traces/recent${qs ? `?${qs}` : ""}`,
    { credentials: FETCH_CREDS },
  );
  if (!res.ok) {
    throw new Error(`getRecentTraces failed: ${res.status}`);
  }
  return res.json();
}
