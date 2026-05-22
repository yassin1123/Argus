// API client for /api/sessions/{session_id}/review — Phase 4 / Week 15.
// Backend at backend/api/review.py is the source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export type ReviewState =
  | "draft"
  | "in_review"
  | "changes_requested"
  | "approved"
  | "delivered";

export type ReviewActionKind =
  | "submit_for_review"
  | "approve"
  | "request_changes"
  | "resubmit"
  | "mark_delivered"
  | "reopen"
  | "auto_revert";

export type FeedbackSeverity = "minor" | "major" | "blocking";

export interface SectionPointer {
  section_path: string;
  note: string;
  severity: FeedbackSeverity;
  resolved: boolean;
  resolved_at?: string | null;
  resolved_by?: string | null;
}

export interface ReviewFeedback {
  overall_note: string;
  section_pointers: SectionPointer[];
  severity: FeedbackSeverity;
}

export interface ReviewHistoryEntry {
  id: string;
  from_state: ReviewState;
  to_state: ReviewState;
  action: ReviewActionKind;
  actor_id: string;
  reviewer_id: string | null;
  feedback: ReviewFeedback | string | null;
  created_at: string;
}

export interface ReviewStatePayload {
  session_id: string;
  review_state: ReviewState;
  review_assigned_to: string | null;
  approved_by: string | null;
  approved_at: string | null;
  submitted_at: string | null;
  submitted_by: string | null;
  history: ReviewHistoryEntry[];
}

export interface TransitionResponse {
  session_id: string;
  from_state: ReviewState;
  to_state: ReviewState;
  action: ReviewActionKind;
  review_record_id: string | null;
  reviewer_id: string | null;
  artifacts_marked_stale: number;
}

export interface BlockedResubmitDetail {
  reason: string;
  blocking_pointer_paths: string[];
}

export class ReviewBlockedError extends Error {
  blocking_pointer_paths: string[];
  constructor(detail: BlockedResubmitDetail) {
    super(detail.reason);
    this.name = "ReviewBlockedError";
    this.blocking_pointer_paths = detail.blocking_pointer_paths;
  }
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

async function readJson(r: Response): Promise<unknown> {
  try {
    return await r.json();
  } catch {
    return await r.text();
  }
}

async function postReview(
  sessionId: string,
  endpoint: string,
  body: Record<string, unknown> = {},
): Promise<TransitionResponse> {
  const r = await apiFetch(`/api/sessions/${sessionId}/review/${endpoint}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await readJson(r);
    // The W15/D3 resubmit gate returns a structured detail object —
    // surface that to callers via a typed error so the UI can render
    // the blocking-paths list.
    if (
      r.status === 409 &&
      typeof detail === "object" &&
      detail !== null &&
      "blocking_pointer_paths" in detail
    ) {
      throw new ReviewBlockedError(detail as BlockedResubmitDetail);
    }
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(`review.${endpoint} ${r.status}: ${msg}`);
  }
  return (await r.json()) as TransitionResponse;
}

export async function submitForReview(
  sessionId: string,
  opts: { reviewer_id?: string } = {},
): Promise<TransitionResponse> {
  return postReview(sessionId, "submit", opts);
}

export async function approveReview(
  sessionId: string,
  opts: { note?: string } = {},
): Promise<TransitionResponse> {
  return postReview(sessionId, "approve", opts);
}

export async function requestChanges(
  sessionId: string,
  body: {
    overall_note: string;
    severity: FeedbackSeverity;
    section_pointers: Array<{
      section_path: string;
      note: string;
      severity: FeedbackSeverity;
    }>;
  },
): Promise<TransitionResponse> {
  return postReview(sessionId, "request-changes", body);
}

export async function markDelivered(sessionId: string): Promise<TransitionResponse> {
  return postReview(sessionId, "mark-delivered");
}

export async function reopenReview(
  sessionId: string,
  opts: { reason?: string } = {},
): Promise<TransitionResponse> {
  return postReview(sessionId, "reopen", opts);
}

export async function getReview(sessionId: string): Promise<ReviewStatePayload> {
  const r = await apiFetch(`/api/sessions/${sessionId}/review`, { method: "GET" });
  if (!r.ok) {
    const detail = await readJson(r);
    throw new Error(`getReview ${r.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return (await r.json()) as ReviewStatePayload;
}

export async function resolvePointer(
  sessionId: string,
  reviewRecordId: string,
  sectionPath: string,
): Promise<{ review_record_id: string; section_path: string; changed: boolean }> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/review/feedback/${reviewRecordId}/resolve-pointer`,
    {
      method: "POST",
      body: JSON.stringify({ section_path: sectionPath }),
    },
  );
  if (!r.ok) {
    const detail = await readJson(r);
    throw new Error(`resolvePointer ${r.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return r.json();
}
