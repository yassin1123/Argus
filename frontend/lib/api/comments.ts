// API client for /api/sessions/{session_id}/comments + /api/comments/{id}/*
// — Phase 4 / Week 16 / Day 2. Backend at backend/api/comments.py is the
// source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export type AnchorType =
  | "engagement"
  | "section"
  | "claim"
  | "text_range"
  | "artifact";

export interface AnchorRef {
  section_path?: string;
  claim_id?: string;
  artifact_id?: string;
  // text_range
  start?: number;
  end?: number;
  quoted_text?: string;
}

export interface CommentRow {
  id: string;
  session_id: string;
  firm_id: string;
  parent_comment_id: string | null;
  anchor_type: AnchorType;
  anchor_ref: AnchorRef;
  body: string;
  mentioned_user_ids: string[];
  author_id: string;
  resolved: boolean;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  edited_at: string | null;
  deleted_at: string | null;
}

export interface CommentThread {
  root: CommentRow;
  replies: CommentRow[];
  resolved: boolean;
  orphaned: boolean;
}

export interface ThreadsResponse {
  session_id: string;
  threads: CommentThread[];
  total: number;
}

export interface CountsResponse {
  by_anchor_type: Record<string, number>;
  by_section_path: Record<string, number>;
  unresolved_total: number;
  total: number;
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

async function ensureOk(r: Response, label: string): Promise<void> {
  if (r.ok) return;
  const detail = await readJson(r);
  const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
  throw new Error(`${label} ${r.status}: ${msg}`);
}

// ---------------------------------------------------------------------------
// List / count
// ---------------------------------------------------------------------------

export async function listThreads(
  sessionId: string,
  opts: {
    anchor_type?: AnchorType;
    resolved?: boolean;
    author_id?: string;
    mentioning?: string;
  } = {},
): Promise<ThreadsResponse> {
  const qs = new URLSearchParams();
  if (opts.anchor_type) qs.set("anchor_type", opts.anchor_type);
  if (opts.resolved !== undefined) qs.set("resolved", String(opts.resolved));
  if (opts.author_id) qs.set("author_id", opts.author_id);
  if (opts.mentioning) qs.set("mentioning", opts.mentioning);
  const suffix = qs.toString();
  const r = await apiFetch(
    `/api/sessions/${sessionId}/comments${suffix ? `?${suffix}` : ""}`,
    { method: "GET" },
  );
  await ensureOk(r, "listThreads");
  return (await r.json()) as ThreadsResponse;
}

// ---------------------------------------------------------------------------
// W16/D4 — grouped overview, bulk resolve, cross-engagement mentions
// ---------------------------------------------------------------------------

export interface OverviewGroup {
  key: string;
  label: string;
  anchor_type: AnchorType;
  anchor_ref: AnchorRef;
  threads: CommentThread[];
  unresolved: number;
  total: number;
}

export interface OverviewResponse {
  groups: OverviewGroup[];
  unresolved_total: number;
  total: number;
}

export async function getOverview(
  sessionId: string,
  opts: { resolved?: boolean; author_id?: string; mentioning?: string } = {},
): Promise<OverviewResponse> {
  const qs = new URLSearchParams();
  if (opts.resolved !== undefined) qs.set("resolved", String(opts.resolved));
  if (opts.author_id) qs.set("author_id", opts.author_id);
  if (opts.mentioning) qs.set("mentioning", opts.mentioning);
  const suffix = qs.toString();
  const r = await apiFetch(
    `/api/sessions/${sessionId}/comments/overview${suffix ? `?${suffix}` : ""}`,
    { method: "GET" },
  );
  await ensureOk(r, "getOverview");
  return (await r.json()) as OverviewResponse;
}

export async function resolveSection(
  sessionId: string,
  sectionPath: string,
): Promise<{ section_path: string; resolved_count: number; resolved_comment_ids: string[] }> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/comments/resolve-section`,
    {
      method: "POST",
      body: JSON.stringify({ section_path: sectionPath }),
    },
  );
  await ensureOk(r, "resolveSection");
  return r.json();
}

export interface MentionsResponse {
  user_id: string;
  firm_id: string;
  mentions: CommentRow[];
  total: number;
}

export async function listMyMentions(
  userId: string,
  opts: { unresolved_only?: boolean; limit?: number } = {},
): Promise<MentionsResponse> {
  const qs = new URLSearchParams();
  if (opts.unresolved_only) qs.set("unresolved_only", "true");
  if (opts.limit) qs.set("limit", String(opts.limit));
  const suffix = qs.toString();
  const r = await apiFetch(
    `/api/users/${userId}/mentions${suffix ? `?${suffix}` : ""}`,
    { method: "GET" },
  );
  await ensureOk(r, "listMyMentions");
  return (await r.json()) as MentionsResponse;
}

export async function getCounts(sessionId: string): Promise<CountsResponse> {
  const r = await apiFetch(`/api/sessions/${sessionId}/comments/count`, {
    method: "GET",
  });
  await ensureOk(r, "getCounts");
  return (await r.json()) as CountsResponse;
}

// ---------------------------------------------------------------------------
// Create / Reply / Edit / Delete
// ---------------------------------------------------------------------------

export interface CreateCommentInput {
  anchor_type: AnchorType;
  anchor_ref?: AnchorRef;
  body: string;
}

export async function createComment(
  sessionId: string,
  input: CreateCommentInput,
): Promise<CommentRow> {
  const r = await apiFetch(`/api/sessions/${sessionId}/comments`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  await ensureOk(r, "createComment");
  return (await r.json()) as CommentRow;
}

export async function replyToComment(
  commentId: string,
  body: string,
): Promise<CommentRow> {
  const r = await apiFetch(`/api/comments/${commentId}/replies`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  await ensureOk(r, "replyToComment");
  return (await r.json()) as CommentRow;
}

export async function editComment(
  commentId: string,
  body: string,
): Promise<CommentRow> {
  const r = await apiFetch(`/api/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify({ body }),
  });
  await ensureOk(r, "editComment");
  return (await r.json()) as CommentRow;
}

export async function deleteComment(
  commentId: string,
): Promise<{ ok: boolean; comment_id: string }> {
  const r = await apiFetch(`/api/comments/${commentId}`, { method: "DELETE" });
  await ensureOk(r, "deleteComment");
  return (await r.json()) as { ok: boolean; comment_id: string };
}

// ---------------------------------------------------------------------------
// Resolve / unresolve
// ---------------------------------------------------------------------------

export async function resolveThread(
  commentId: string,
): Promise<{ ok: boolean; comment_id: string; resolved: boolean }> {
  const r = await apiFetch(`/api/comments/${commentId}/resolve`, {
    method: "POST",
  });
  await ensureOk(r, "resolveThread");
  return (await r.json()) as { ok: boolean; comment_id: string; resolved: boolean };
}

export async function unresolveThread(
  commentId: string,
): Promise<{ ok: boolean; comment_id: string; resolved: boolean }> {
  const r = await apiFetch(`/api/comments/${commentId}/unresolve`, {
    method: "POST",
  });
  await ensureOk(r, "unresolveThread");
  return (await r.json()) as { ok: boolean; comment_id: string; resolved: boolean };
}

// ---------------------------------------------------------------------------
// Mention slug helpers — match the W16/D2 backend parser
//   (backend/core/comments/mentions.py:slug_for_user)
// ---------------------------------------------------------------------------

export interface FirmMemberLite {
  user_id: string;
  email?: string;
  full_name?: string;
}

export function slugForUser(user: { email?: string }): string {
  const email = (user.email || "").trim();
  if (!email || !email.includes("@")) return "";
  const local = email.split("@", 1)[0].toLowerCase();
  return local.replace(/[^a-z0-9]+/g, ".").replace(/^\.+|\.+$/g, "");
}

/**
 * Build {slug -> user_id} for an entire firm, applying the same
 * deterministic collision-suffix rule the backend uses
 * (sarah.kim, sarah.kim2, …) so what the autocomplete shows is what
 * the parser will resolve.
 *
 * Order of `members` decides who keeps the bare slug — pass them
 * sorted by (created_at, id) ascending to match the backend's
 * firm_memberships ORDER BY.
 */
export function buildSlugIndex(
  members: FirmMemberLite[],
): Array<{ slug: string; user_id: string; full_name?: string }> {
  const counts = new Map<string, number>();
  const out: Array<{ slug: string; user_id: string; full_name?: string }> = [];
  for (const m of members) {
    const base = slugForUser(m);
    if (!base) continue;
    const n = counts.get(base) ?? 0;
    counts.set(base, n + 1);
    const slug = n === 0 ? base : `${base}${n + 1}`;
    out.push({ slug, user_id: m.user_id, full_name: m.full_name });
  }
  return out;
}
