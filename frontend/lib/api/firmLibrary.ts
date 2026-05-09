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

/**
 * Multipart POST to /api/firms/{firm_id}/library matching the Day 1
 * backend signature (Form fields + File). Throws Error with the
 * server's `detail` message on non-2xx.
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
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail || `Upload failed (${res.status})`);
  }
  return (await res.json()) as UploadFirmContentResult;
}
