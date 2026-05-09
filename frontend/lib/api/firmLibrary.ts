// API client for /api/firms/{firm_id}/library (Phase 2 / Week 5 / Day 2 ).
// Day 1 backend at backend/api/firm_library.py is the source of truth for
// the response shapes.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export type FirmContentCategory =
  | "playbook"
  | "sector_primer"
  | "prior_report"
  | "framework"
  | "methodology"
  | "other";

export interface FirmContent {
  id: string;
  firm_id: string;
  title: string;
  category: FirmContentCategory;
  description: string | null;
  intended_modes: string[];
  sector_tags: string[];
  source_filename: string | null;
  file_hash: string | null;
  trust_level: string;
  uploaded_by: string | null;
  uploaded_at: string;
  retired_at: string | null;
  retired_by: string | null;
  chunk_count: number;
  metadata: Record<string, unknown>;
}

export interface UploadFirmContentResult {
  firm_content: FirmContent;
  ingest: {
    cached: boolean;
    chunks_written: number;
  };
}

export interface UploadFirmContentInput {
  title: string;
  category: FirmContentCategory;
  description?: string;
  intendedModes?: string[];
  sectorTags?: string[];
  file: File;
}

async function jsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail || `${fallback} (${res.status})`);
  }
  return (await res.json()) as T;
}

/**
 * Multipart POST to /api/firms/{firm_id}/library. Throws Error with the
 * server's `detail` message on non-2xx (e.g. 403 admin required).
 */
export async function uploadFirmContent(
  firmId: string,
  input: UploadFirmContentInput,
): Promise<UploadFirmContentResult> {
  const fd = new FormData();
  fd.append("title", input.title);
  fd.append("category", input.category);
  if (input.description) fd.append("description", input.description);
  if (input.intendedModes && input.intendedModes.length > 0) {
    fd.append("intended_modes", input.intendedModes.join(","));
  }
  if (input.sectorTags && input.sectorTags.length > 0) {
    fd.append("sector_tags", input.sectorTags.join(","));
  }
  fd.append("file", input.file);

  const res = await fetch(`${BASE_URL}/api/firms/${firmId}/library`, {
    method: "POST",
    credentials: FETCH_CREDS,
    body: fd,
  });
  return jsonOrThrow<UploadFirmContentResult>(res, "Upload failed");
}

// ---------------------------------------------------------------------------
// Day 3 — list / get-one / edit / retire
// ---------------------------------------------------------------------------


export interface ChunkPreview {
  id: string;
  content: string;
  position: number;
  page: number | null;
  section_heading: string | null;
  source_filename: string | null;
}

export interface ListFirmContentParams {
  category?: FirmContentCategory;
  sector?: string;
  mode?: string;
  includeRetired?: boolean;
}

export async function listFirmContent(
  firmId: string,
  params: ListFirmContentParams = {},
): Promise<FirmContent[]> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.sector) qs.set("sector", params.sector);
  if (params.mode) qs.set("mode", params.mode);
  if (params.includeRetired) qs.set("include_retired", "true");
  const qsPart = qs.toString();
  const url = `${BASE_URL}/api/firms/${firmId}/library${qsPart ? `?${qsPart}` : ""}`;
  const res = await fetch(url, { credentials: FETCH_CREDS, cache: "no-store" });
  const body = await jsonOrThrow<{ firm_content: FirmContent[] }>(res, "List failed");
  return body.firm_content;
}

export async function getFirmContent(
  firmId: string,
  contentId: string,
): Promise<{ firm_content: FirmContent; chunk_preview: ChunkPreview[] }> {
  const res = await fetch(
    `${BASE_URL}/api/firms/${firmId}/library/${contentId}`,
    { credentials: FETCH_CREDS, cache: "no-store" },
  );
  return jsonOrThrow(res, "Fetch failed");
}

export interface EditFirmContentInput {
  title?: string;
  description?: string;
  intendedModes?: string[];
  sectorTags?: string[];
}

export async function editFirmContent(
  firmId: string,
  contentId: string,
  input: EditFirmContentInput,
): Promise<FirmContent> {
  const body = {
    title: input.title,
    description: input.description,
    intended_modes: input.intendedModes,
    sector_tags: input.sectorTags,
  };
  const res = await fetch(
    `${BASE_URL}/api/firms/${firmId}/library/${contentId}`,
    {
      method: "POST",
      credentials: FETCH_CREDS,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  const r = await jsonOrThrow<{ firm_content: FirmContent }>(res, "Edit failed");
  return r.firm_content;
}

export async function retireFirmContent(
  firmId: string,
  contentId: string,
): Promise<{ firm_content: FirmContent; already_retired: boolean }> {
  const res = await fetch(
    `${BASE_URL}/api/firms/${firmId}/library/${contentId}/retire`,
    { method: "POST", credentials: FETCH_CREDS },
  );
  return jsonOrThrow(res, "Retire failed");
}
