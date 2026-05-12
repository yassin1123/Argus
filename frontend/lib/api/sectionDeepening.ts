// API client for /api/sessions/{session_id}/deepen — Phase 2 / Week 9 / Day 2.
// Backend at backend/api/section_deepening.py is the source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export type DeepeningStatus = "queued" | "running" | "complete" | "failed";

export interface Deepening {
  id: string;
  section_path: string;
  depth_directive: string | null;
  status: DeepeningStatus;
  failure_reason: string | null;
  new_evidence_chunks_used: number;
  cost_usd: number;
  wall_seconds: number;
  created_at: string;
  completed_at: string | null;
}

export interface DeepeningDetail extends Deepening {
  session_id: string;
  firm_id: string;
  triggered_by: string | null;
  original_section_json: unknown;
  deepened_section_json: unknown;
  new_claim_ids: string[];
  // W9/D3: accept/reject state surfaces on the detail endpoint.
  accepted_at?: string | null;
  accepted_by?: string | null;
  rejected_at?: string | null;
  rejected_by?: string | null;
}

export interface AcceptResponse {
  deepening_id: string;
  status: "accepted" | "already_accepted";
  section_path?: string;
  accepted_at?: string;
  new_payload?: Record<string, unknown>;
}

export interface RejectResponse {
  deepening_id: string;
  status: "rejected" | "already_rejected";
  section_path?: string;
  rejected_at?: string;
}

export interface TriggerDeepeningResponse {
  status: "queued";
  section_path: string;
  depth_directive: string | null;
  session_id: string;
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE_URL}${path}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
}

export async function triggerDeepening(
  sessionId: string,
  sectionPath: string,
  depthDirective?: string,
): Promise<TriggerDeepeningResponse> {
  if (!sectionPath.trim()) {
    throw new Error("section_path must be non-empty");
  }
  const r = await apiFetch(`/api/sessions/${sessionId}/deepen`, {
    method: "POST",
    body: JSON.stringify({
      section_path: sectionPath,
      depth_directive: depthDirective || null,
    }),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`triggerDeepening failed: ${r.status} ${text.slice(0, 200)}`);
  }
  return (await r.json()) as TriggerDeepeningResponse;
}

export async function pollDeepening(
  sessionId: string,
  deepeningId: string,
): Promise<DeepeningDetail> {
  const r = await apiFetch(`/api/sessions/${sessionId}/deepen/${deepeningId}`);
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`pollDeepening failed: ${r.status} ${text.slice(0, 200)}`);
  }
  return (await r.json()) as DeepeningDetail;
}

export async function listDeepenings(sessionId: string): Promise<Deepening[]> {
  const r = await apiFetch(`/api/sessions/${sessionId}/deepen`);
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`listDeepenings failed: ${r.status} ${text.slice(0, 200)}`);
  }
  return (await r.json()) as Deepening[];
}

export async function acceptDeepening(
  sessionId: string,
  deepeningId: string,
): Promise<AcceptResponse> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/deepen/${deepeningId}/accept`,
    { method: "POST" },
  );
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`acceptDeepening failed: ${r.status} ${text.slice(0, 200)}`);
  }
  return (await r.json()) as AcceptResponse;
}

export async function rejectDeepening(
  sessionId: string,
  deepeningId: string,
): Promise<RejectResponse> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/deepen/${deepeningId}/reject`,
    { method: "POST" },
  );
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`rejectDeepening failed: ${r.status} ${text.slice(0, 200)}`);
  }
  return (await r.json()) as RejectResponse;
}

// Section-path → human-readable display label.
// Auto-decided per W9/D2 spec; kept here so both the section picker
// affordance and the modal header use the same vocabulary.
const SECTION_LABELS: Record<string, string> = {
  summary: "Executive summary",
  key_reasons: "Key reasons",
  risks: "Risks",
  counterarguments: "Counterarguments",
  next_steps: "Next steps",
  target_overview: "Target overview",
  financial_profile: "Financial profile",
  synergy_estimate: "Synergy estimate",
  risks_and_mitigations: "Risks and mitigations",
  integration_plan: "Integration plan",
  valuation_range: "Valuation range",
  deal_structure_implications: "Deal structure implications",
  "frameworks.two_by_two": "2x2 matrix",
  "frameworks.porters_five_forces": "Porter's Five Forces",
  "frameworks.value_chain": "Value Chain",
};

export function sectionDisplayName(path: string): string {
  return (
    SECTION_LABELS[path] ||
    path
      .split(".")
      .map((p) => p.replace(/_/g, " "))
      .join(" › ")
  );
}

// Per W9/D2 hard rule: don't deepen the recommendation. It's the
// top-down conclusion, re-derived from the sections that change.
const DEEPENABLE_PATHS = new Set<string>([
  "summary",
  "key_reasons",
  "risks",
  "counterarguments",
  "next_steps",
  "target_overview",
  "financial_profile",
  "synergy_estimate",
  "risks_and_mitigations",
  "integration_plan",
  "valuation_range",
  "deal_structure_implications",
  "frameworks.two_by_two",
  "frameworks.porters_five_forces",
  "frameworks.value_chain",
]);

export function isDeepenable(path: string): boolean {
  return DEEPENABLE_PATHS.has(path);
}
