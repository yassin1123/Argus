// API client for /api/.../feedback + /api/pilot/* (Phase 5 / Week 24 / Day 3).
// One-click, optional pilot feedback. Mirrors backend/api/pilot_feedback.py.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

async function req<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export type ClaimAssessment = "correct" | "wrong_supported" | "wrong_flagged" | "unsure";

export function postClaimFeedback(
  sessionId: string,
  claimId: string,
  body: { consultant_assessment: ClaimAssessment; verdict_at_feedback?: string; note?: string },
): Promise<{ ok: boolean; feedback_id: string }> {
  return req(`/api/sessions/${sessionId}/claims/${encodeURIComponent(claimId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function postArtifactRating(
  sessionId: string,
  body: { rating: number; artifact_id?: string; artifact_type?: string; comment?: string },
): Promise<{ ok: boolean; rating_id: string }> {
  return req(`/api/sessions/${sessionId}/artifacts/rating`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface CheckinQuestion {
  id: string;
  type: "text" | "scale_1_5" | "yes_no";
  prompt: string;
}

export function getCheckinForm(): Promise<{ questions: CheckinQuestion[] }> {
  return req(`/api/pilot/checkin/form`, { method: "GET" });
}

export function submitCheckin(
  responses: Record<string, unknown>,
  weekBucket?: string,
): Promise<{ ok: boolean; id: string; week_bucket: string }> {
  return req(`/api/pilot/checkin`, {
    method: "POST",
    body: JSON.stringify({ responses, week_bucket: weekBucket }),
  });
}

export interface PilotHealth {
  firm_id: string;
  claim_feedback: {
    total: number;
    counts: Record<ClaimAssessment, number>;
    pct: Record<ClaimAssessment, number>;
  };
  artifact_ratings: {
    average_rating: number;
    rating_count: number;
    by_type: { artifact_type: string | null; average_rating: number; count: number }[];
  };
  edit_rate: { average_edit_fraction: number; average_edit_pct: number; engagement_count: number };
  checkin_trend: { week_bucket: string; responses: Record<string, unknown>; updated_at: string | null }[];
}

export function getPilotHealth(firmId?: string): Promise<PilotHealth> {
  const qs = firmId ? `?firm_id=${encodeURIComponent(firmId)}` : "";
  return req(`/api/pilot/health${qs}`, { method: "GET" });
}
