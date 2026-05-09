import type {
  Artifact,
  ArtifactStatus,
  ArtifactType,
  ChunkSearchResponse,
  EngagementMember,
  EngagementRole,
  EvidenceGraph,
  Session,
  SessionDetail,
  SourceItem,
  SourceScope,
  TrustLevel,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// All API calls send the session cookie cross-origin.
const FETCH_CREDS: RequestCredentials = "include";

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BASE_URL}${path}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
    ...init,
    headers: {
      ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
}

async function jsonOrThrow<T>(res: Response, fallback = "Request failed"): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText || fallback);
  }
  return res.json() as Promise<T>;
}

// ---- Auth ----------------------------------------------------------------

export type AuthUser = {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  default_firm_id: string | null;
  default_firm_role: "admin" | "member" | null;
};

export async function register(email: string, password: string, full_name = ""): Promise<{ user: AuthUser }> {
  const res = await apiFetch(`/api/auth/register`, {
    method: "POST",
    body: JSON.stringify({ email, password, full_name }),
  });
  return jsonOrThrow<{ user: AuthUser }>(res, "Registration failed");
}

export async function login(email: string, password: string): Promise<{ user: AuthUser }> {
  const res = await apiFetch(`/api/auth/login`, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return jsonOrThrow<{ user: AuthUser }>(res, "Login failed");
}

export async function logout(): Promise<void> {
  await apiFetch(`/api/auth/logout`, { method: "POST" });
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const res = await apiFetch(`/api/auth/me`);
  if (res.status === 401) return null;
  if (!res.ok) return null;
  const data = (await res.json()) as { user: AuthUser };
  return data.user;
}

// ---- Sessions / engagements ---------------------------------------------

export async function createSession(
  query: string,
  title?: string,
  reportMode: string = "general"
): Promise<{ session_id: string; status: string; report_mode?: string }> {
  const res = await apiFetch(`/api/sessions`, {
    method: "POST",
    body: JSON.stringify({
      query,
      title: title?.trim() || query.trim().slice(0, 80),
      report_mode: reportMode,
    }),
  });
  return jsonOrThrow(res);
}

export async function generateIntakeQuestions(
  sessionId: string
): Promise<{ questions: Array<Record<string, string>> }> {
  const res = await apiFetch(`/api/sessions/${sessionId}/intake/generate`, { method: "POST" });
  return jsonOrThrow(res);
}

export async function getChatHistory(sessionId: string): Promise<
  Array<{
    id: string;
    role: string;
    content: string;
    turn_index: number;
    intent?: string | null;
    created_at?: string | null;
  }>
> {
  const res = await apiFetch(`/api/sessions/${sessionId}/chat`);
  if (!res.ok) throw new Error("Failed to load chat");
  return res.json();
}

export async function sendChatMessage(
  sessionId: string,
  message: string
): Promise<{
  reply: string;
  pipeline_triggered: boolean;
  turn_id: string;
  intent?: string;
  follow_up_question?: string;
}> {
  const res = await apiFetch(`/api/sessions/${sessionId}/chat`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
  return jsonOrThrow(res);
}

export async function submitIntakeAnswers(
  sessionId: string,
  answers: Array<{ id: string; answer: string }>
): Promise<{ ok: boolean }> {
  const res = await apiFetch(`/api/sessions/${sessionId}/intake/submit`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
  return jsonOrThrow(res);
}

export async function runSession(sessionId: string): Promise<{ status: string }> {
  const res = await apiFetch(`/api/sessions/${sessionId}/run`, { method: "POST" });
  return jsonOrThrow(res);
}

export async function getSession(id: string): Promise<SessionDetail> {
  const res = await apiFetch(`/api/workspaces/${id}`);
  if (!res.ok) throw new Error("Failed to load session");
  return res.json();
}

export async function getEvidenceGraph(id: string): Promise<EvidenceGraph> {
  const res = await apiFetch(`/api/workspaces/${id}/graph`);
  if (!res.ok) throw new Error("Failed to load evidence graph");
  return res.json();
}

// ---- Artifacts ----------------------------------------------------------

export async function listArtifacts(engagementId: string): Promise<Artifact[]> {
  const res = await apiFetch(`/api/artifacts?engagement_id=${encodeURIComponent(engagementId)}`);
  if (!res.ok) throw new Error("Failed to load artifacts");
  const data = (await res.json()) as { artifacts: Artifact[] };
  return data.artifacts;
}

export async function createArtifact(
  engagementId: string,
  type: ArtifactType = "memo",
  title?: string,
): Promise<Artifact> {
  const res = await apiFetch(`/api/artifacts`, {
    method: "POST",
    body: JSON.stringify({ engagement_id: engagementId, type, title }),
  });
  const data = await jsonOrThrow<{ artifact: Artifact }>(res, "Failed to create artifact");
  return data.artifact;
}

export async function getArtifact(artifactId: string): Promise<Artifact> {
  const res = await apiFetch(`/api/artifacts/${artifactId}`);
  if (!res.ok) throw new Error("Failed to load artifact");
  const data = (await res.json()) as { artifact: Artifact };
  return data.artifact;
}

export async function patchArtifact(
  artifactId: string,
  patch: { title?: string; status?: ArtifactStatus; document_json?: Record<string, unknown> },
): Promise<Artifact> {
  const res = await apiFetch(`/api/artifacts/${artifactId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  const data = await jsonOrThrow<{ artifact: Artifact }>(res, "Failed to save artifact");
  return data.artifact;
}

export async function exportArtifactDocx(artifactId: string): Promise<Blob> {
  const res = await apiFetch(`/api/artifacts/${artifactId}/export?format=docx`);
  if (!res.ok) throw new Error("Failed to export artifact");
  return res.blob();
}

// ---- Sources / library --------------------------------------------------

export async function listEngagementSources(engagementId: string): Promise<SourceItem[]> {
  const res = await apiFetch(`/api/sources?engagement_id=${encodeURIComponent(engagementId)}`);
  if (!res.ok) throw new Error("Failed to load sources");
  const data = (await res.json()) as { sources: SourceItem[] };
  return data.sources;
}

export async function listLibrarySources(): Promise<SourceItem[]> {
  const res = await apiFetch(`/api/library/sources`);
  if (!res.ok) throw new Error("Failed to load library");
  const data = (await res.json()) as { sources: SourceItem[] };
  return data.sources;
}

export async function patchSource(
  sourceId: string,
  patch: { title?: string; trust_level?: TrustLevel; scope?: SourceScope; notes?: string },
): Promise<SourceItem> {
  const res = await apiFetch(`/api/sources/${sourceId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  const data = await jsonOrThrow<{ source: SourceItem }>(res, "Failed to update source");
  return data.source;
}

export async function searchChunks(
  engagementId: string,
  q: string,
  opts: { mode?: "hybrid" | "vector" | "keyword"; k?: number } = {},
): Promise<ChunkSearchResponse> {
  const params = new URLSearchParams({
    engagement_id: engagementId,
    q,
    mode: opts.mode ?? "hybrid",
    k: String(opts.k ?? 20),
  });
  const res = await apiFetch(`/api/sources/search?${params.toString()}`);
  if (!res.ok) throw new Error("Search failed");
  return res.json();
}

export async function deleteSource(sourceId: string): Promise<void> {
  const res = await apiFetch(`/api/sources/${sourceId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Failed to delete source");
  }
}

// ---- Engagement memberships --------------------------------------------

export async function listEngagementMembers(engagementId: string): Promise<EngagementMember[]> {
  const res = await apiFetch(`/api/engagements/${engagementId}/members`);
  if (!res.ok) throw new Error("Failed to load members");
  const data = (await res.json()) as { members: EngagementMember[] };
  return data.members;
}

export async function addEngagementMember(
  engagementId: string,
  email: string,
  role: EngagementRole = "member",
): Promise<EngagementMember> {
  const res = await apiFetch(`/api/engagements/${engagementId}/members`, {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
  return jsonOrThrow<EngagementMember>(res, "Failed to add member");
}

export async function removeEngagementMember(
  engagementId: string,
  userId: string,
): Promise<void> {
  const res = await apiFetch(`/api/engagements/${engagementId}/members/${userId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Failed to remove member");
  }
}

export async function listSessions(): Promise<Session[]> {
  const res = await apiFetch(`/api/sessions`);
  if (!res.ok) throw new Error("Failed to list sessions");
  return res.json();
}

export async function uploadFile(sessionId: string, file: File): Promise<unknown> {
  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("file", file);
  const res = await apiFetch(`/api/inputs/upload`, { method: "POST", body: formData });
  return jsonOrThrow(res);
}

export async function submitUrl(sessionId: string, url: string): Promise<unknown> {
  const res = await apiFetch(`/api/inputs/url`, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, url }),
  });
  return jsonOrThrow(res);
}

export type ExportFormat = "pdf" | "memo" | "client" | "pptx";

export async function downloadExport(sessionId: string, format: ExportFormat): Promise<Blob> {
  const path =
    format === "pdf"
      ? "pdf"
      : format === "memo"
        ? "memo"
        : format === "client"
          ? "report"
          : "pptx";
  const res = await apiFetch(`/api/exports/${path}/${sessionId}`);
  if (!res.ok) throw new Error("Export not available");
  return res.blob();
}

/** @deprecated use downloadExport(id, "pdf") */
export async function downloadPDF(sessionId: string): Promise<Blob> {
  return downloadExport(sessionId, "pdf");
}
