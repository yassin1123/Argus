// API client for /api/collaboration surfaces — Phase 4 / Week 17.
// Backend at backend/api/collaboration.py is the source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

// ---------------------------------------------------------------------------
// Types — mirror the backend dataclasses
// ---------------------------------------------------------------------------

export type EngagementRole =
  | "lead"
  | "contributor"
  | "reviewer"
  | "observer";

export type SectionStatus =
  | "not_started"
  | "in_progress"
  | "needs_review"
  | "done";

export type TaskPriority = "high" | "medium" | "low";

export type DerivedTaskType =
  | "section_incomplete"
  | "change_request"
  | "mention"
  | "comment_on_owned_section";

export interface EngagementMember {
  id: string;
  session_id: string;
  firm_id: string;
  user_id: string;
  role: EngagementRole;
  assigned_by: string | null;
  assigned_at: string;
  removed_at: string | null;
}

export interface SectionAssignment {
  id: string;
  session_id: string;
  firm_id: string;
  section_path: string;
  assigned_to: string | null;
  assigned_by: string | null;
  status: SectionStatus;
  assigned_at: string;
  updated_at: string;
}

export interface CoverageEntry {
  section_path: string;
  assigned: boolean;
  assigned_to: string | null;
  assigned_by: string | null;
  status: SectionStatus;
  assignment_id: string | null;
  updated_at: string | null;
}

export interface CoverageMap {
  session_id: string;
  entries: CoverageEntry[];
  unassigned_count: number;
  by_status: Record<string, number>;
  ready_to_submit: boolean;
}

export interface UnifiedTask {
  source: "derived" | "explicit";
  task_type: string;  // DerivedTaskType | "explicit"
  session_id: string;
  section_path: string | null;
  source_ref: string;
  summary: string;
  priority: TaskPriority;
  created_at: string;
  extra: Record<string, unknown>;
}

export interface EngagementBucket {
  session_id: string;
  engagement_title: string;
  tasks: UnifiedTask[];
  counts: { high: number; medium: number; low: number; total: number };
}

export interface MyWork {
  user_id: string;
  scope: string;
  tasks: UnifiedTask[];
  by_engagement: Record<string, EngagementBucket>;
  totals: { high: number; medium: number; low: number };
}

export interface ExplicitTask {
  id: string;
  session_id: string;
  firm_id: string;
  title: string;
  assigned_to: string | null;
  created_by: string;
  section_path: string | null;
  done: boolean;
  done_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

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
// Members (W17/D1)
// ---------------------------------------------------------------------------

export async function listMembers(sessionId: string): Promise<EngagementMember[]> {
  const r = await apiFetch(`/api/sessions/${sessionId}/members`, { method: "GET" });
  await ensureOk(r, "listMembers");
  return ((await r.json()) as { members: EngagementMember[] }).members;
}

export async function assignMember(
  sessionId: string, user_id: string, role: EngagementRole,
): Promise<EngagementMember> {
  const r = await apiFetch(`/api/sessions/${sessionId}/members`, {
    method: "POST",
    body: JSON.stringify({ user_id, role }),
  });
  await ensureOk(r, "assignMember");
  return (await r.json()) as EngagementMember;
}

export async function changeMemberRole(
  sessionId: string, user_id: string, role: EngagementRole,
): Promise<EngagementMember> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/members/${user_id}`,
    { method: "PATCH", body: JSON.stringify({ role }) },
  );
  await ensureOk(r, "changeMemberRole");
  return (await r.json()) as EngagementMember;
}

export async function removeMember(
  sessionId: string, user_id: string,
): Promise<{ ok: boolean }> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/members/${user_id}`,
    { method: "DELETE" },
  );
  await ensureOk(r, "removeMember");
  return (await r.json()) as { ok: boolean };
}

// ---------------------------------------------------------------------------
// Section ownership (W17/D2)
// ---------------------------------------------------------------------------

export async function getCoverage(sessionId: string): Promise<CoverageMap> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/sections/coverage`,
    { method: "GET" },
  );
  await ensureOk(r, "getCoverage");
  return (await r.json()) as CoverageMap;
}

export async function listAssignments(
  sessionId: string,
): Promise<SectionAssignment[]> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/sections/assignments`,
    { method: "GET" },
  );
  await ensureOk(r, "listAssignments");
  return ((await r.json()) as { assignments: SectionAssignment[] }).assignments;
}

export async function assignSection(
  sessionId: string, section_path: string, assigned_to: string,
): Promise<SectionAssignment> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/sections/assign`,
    { method: "POST", body: JSON.stringify({ section_path, assigned_to }) },
  );
  await ensureOk(r, "assignSection");
  return (await r.json()) as SectionAssignment;
}

export async function setSectionStatus(
  sessionId: string, section_path: string, status: SectionStatus,
): Promise<SectionAssignment> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/sections/${encodeURIComponent(section_path)}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
  await ensureOk(r, "setSectionStatus");
  return (await r.json()) as SectionAssignment;
}

export async function unassignSection(
  sessionId: string, section_path: string,
): Promise<SectionAssignment> {
  const r = await apiFetch(
    `/api/sessions/${sessionId}/sections/${encodeURIComponent(section_path)}`,
    { method: "DELETE" },
  );
  await ensureOk(r, "unassignSection");
  return (await r.json()) as SectionAssignment;
}

// ---------------------------------------------------------------------------
// My work + tasks (W17/D3)
// ---------------------------------------------------------------------------

export async function getMyWork(): Promise<MyWork> {
  const r = await apiFetch(`/api/me/work`, { method: "GET" });
  await ensureOk(r, "getMyWork");
  return (await r.json()) as MyWork;
}

export async function getSessionWork(
  sessionId: string, user_id?: string,
): Promise<MyWork> {
  const qs = user_id ? `?user_id=${encodeURIComponent(user_id)}` : "";
  const r = await apiFetch(
    `/api/sessions/${sessionId}/work${qs}`, { method: "GET" },
  );
  await ensureOk(r, "getSessionWork");
  return (await r.json()) as MyWork;
}

export async function listSessionTasks(
  sessionId: string, include_done = true,
): Promise<ExplicitTask[]> {
  const qs = include_done ? "" : "?include_done=false";
  const r = await apiFetch(
    `/api/sessions/${sessionId}/tasks${qs}`, { method: "GET" },
  );
  await ensureOk(r, "listSessionTasks");
  return ((await r.json()) as { tasks: ExplicitTask[] }).tasks;
}

export async function createTask(
  sessionId: string,
  input: { title: string; assigned_to?: string; section_path?: string },
): Promise<ExplicitTask> {
  const r = await apiFetch(`/api/sessions/${sessionId}/tasks`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  await ensureOk(r, "createTask");
  return (await r.json()) as ExplicitTask;
}

export async function completeTask(taskId: string): Promise<ExplicitTask> {
  const r = await apiFetch(`/api/tasks/${taskId}/complete`, { method: "POST" });
  await ensureOk(r, "completeTask");
  return (await r.json()) as ExplicitTask;
}

// ---------------------------------------------------------------------------
// Role + status display labels
// ---------------------------------------------------------------------------

export const ROLE_LABEL: Record<EngagementRole, string> = {
  lead: "Lead",
  contributor: "Contributor",
  reviewer: "Reviewer",
  observer: "Observer",
};

export const STATUS_LABEL: Record<SectionStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  needs_review: "Needs review",
  done: "Done",
};

export const STATUS_COLOR: Record<SectionStatus, { bg: string; fg: string; border: string }> = {
  not_started:  { bg: "#f3f4f6", fg: "#374151", border: "#d1d5db" },
  in_progress:  { bg: "#dbeafe", fg: "#1e40af", border: "#93c5fd" },
  needs_review: { bg: "#fef3c7", fg: "#92400e", border: "#fcd34d" },
  done:         { bg: "#dcfce7", fg: "#166534", border: "#86efac" },
};
