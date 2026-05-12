// API client for /api/sessions/{id}/exports — Phase 3 / Week 10 / Day 2-3.
// Backend at backend/api/session_exports.py is the source of truth.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export type ExportStatus = "generating" | "ready" | "failed";

export type ArtifactType =
  | "memo"
  | "one_pager"
  | "deck"
  | "excel_model"
  | "email"
  | "interview_guide";

export type ArtifactFormat =
  | "html"
  | "pdf"
  | "pptx"
  | "xlsx"
  | "docx"
  | "md"
  | "json";

export interface CreateExportResponse {
  artifact_id: string;
  session_id: string;
  artifact_type: ArtifactType;
  format: ArtifactFormat;
  status: ExportStatus;
  file_size_bytes: number | null;
  claim_citation_count: number;
  generation_wall_seconds: number;
  failure_reason: string | null;
  metadata: Record<string, unknown>;
}

export interface ExportArtifact {
  id: string;
  session_id?: string;
  firm_id?: string;
  artifact_type: ArtifactType;
  format: ArtifactFormat;
  status: ExportStatus;
  file_path?: string | null;
  file_size_bytes: number | null;
  claim_citation_count: number;
  generation_wall_seconds: number;
  generated_by?: string | null;
  generated_at: string;
  metadata: Record<string, unknown>;
  failure_reason: string | null;
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

export async function createExport(
  sessionId: string,
  artifactType: ArtifactType,
  format: ArtifactFormat,
): Promise<CreateExportResponse> {
  const r = await apiFetch(`/api/sessions/${sessionId}/exports`, {
    method: "POST",
    body: JSON.stringify({
      artifact_type: artifactType,
      format,
    }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`createExport ${r.status}: ${detail}`);
  }
  return (await r.json()) as CreateExportResponse;
}

export async function getExport(
  sessionId: string,
  artifactId: string,
): Promise<ExportArtifact> {
  const r = await apiFetch(`/api/sessions/${sessionId}/exports/${artifactId}`);
  if (!r.ok) {
    throw new Error(`getExport ${r.status}`);
  }
  return (await r.json()) as ExportArtifact;
}

export async function listExports(sessionId: string): Promise<ExportArtifact[]> {
  const r = await apiFetch(`/api/sessions/${sessionId}/exports`);
  if (!r.ok) {
    throw new Error(`listExports ${r.status}`);
  }
  return (await r.json()) as ExportArtifact[];
}

export function downloadUrl(sessionId: string, artifactId: string): string {
  return `${BASE_URL}/api/sessions/${sessionId}/exports/${artifactId}/download`;
}
