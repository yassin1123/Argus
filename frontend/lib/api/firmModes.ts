// API client for /api/firms/{firm_id}/modes (Phase 2 / Week 6 / Day 3 ).
// Day 2 backend at backend/api/firm_modes.py is the source of truth for
// response shapes.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

export type LayerName = "built_in" | "firm" | "engagement";

export const ALLOWED_SOURCE_TYPES = [
  "uploaded",
  "sec_filing",
  "transcript",
  "news",
  "ch_filing",
  "web",
  "firm_library",
] as const;
export type SourceTypeLiteral = (typeof ALLOWED_SOURCE_TYPES)[number];

export const ALLOWED_TRUST_TIERS = [
  "firm_vetted",
  "credible_external",
  "web_general",
  "contested",
] as const;
export type TrustTierLiteral = (typeof ALLOWED_TRUST_TIERS)[number];

export interface ResolvedMode {
  name: string;
  display_name: string;
  description: string;
  required_branches: string[];
  reasoning_slots: string[];
  source_priorities_default: string[];
  trust_tier_rules: Record<string, string>;
  writer_overlay: string;
  planner_overlay: string;
  min_evidence_objects: number;
  metadata: Record<string, unknown>;
  layer_provenance: Record<string, LayerName>;
}

export interface FirmMode {
  id: string;
  firm_id: string;
  name: string;
  base_mode: string | null;
  config: ModeConfigPayload;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  retired_at: string | null;
}

export interface ModeListItem {
  name: string;
  is_builtin: boolean;
  has_firm_override: boolean;
  firm_override: FirmMode | null;
}

/** Shape of the JSON we send to POST/PATCH; every field is optional. */
export interface ModeConfigPayload {
  display_name?: string;
  description?: string;
  required_branches?: string[];
  reasoning_slots?: string[];
  source_priorities_default?: string[];
  trust_tier_rules?: Record<string, string>;
  writer_overlay?: string;
  planner_overlay?: string;
  min_evidence_objects?: number;
  metadata?: Record<string, unknown>;
}

/** Structured 4xx error body the server returns on validation failures. */
export class FirmModeApiError extends Error {
  status: number;
  code: string | null;
  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function jsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as
      | { detail?: string | { error?: string; message?: string } }
      | Record<string, unknown>;
    const detail = (body as { detail?: unknown }).detail;
    if (detail && typeof detail === "object") {
      const d = detail as { error?: string; message?: string };
      throw new FirmModeApiError(
        d.message || fallback,
        res.status,
        d.error ?? null,
      );
    }
    throw new FirmModeApiError(
      typeof detail === "string" ? detail : fallback,
      res.status,
      null,
    );
  }
  return (await res.json()) as T;
}

export async function listFirmModes(
  firmId: string,
  options: { includeRetired?: boolean } = {},
): Promise<ModeListItem[]> {
  const qs = options.includeRetired ? "?include_retired=true" : "";
  const res = await fetch(`${BASE_URL}/api/firms/${firmId}/modes${qs}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
  });
  const body = await jsonOrThrow<{ modes: ModeListItem[] }>(res, "List failed");
  return body.modes;
}

export async function getFirmMode(
  firmId: string,
  name: string,
): Promise<{ name: string; resolved: ResolvedMode; firm_override: FirmMode | null }> {
  const res = await fetch(`${BASE_URL}/api/firms/${firmId}/modes/${encodeURIComponent(name)}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
  });
  return jsonOrThrow(res, "Fetch failed");
}

export interface CreateFirmModeInput {
  name: string;
  base_mode?: string | null;
  config: ModeConfigPayload;
}

export async function createFirmMode(
  firmId: string,
  input: CreateFirmModeInput,
): Promise<FirmMode> {
  const res = await fetch(`${BASE_URL}/api/firms/${firmId}/modes`, {
    method: "POST",
    credentials: FETCH_CREDS,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      base_mode: input.base_mode ?? null,
      config: input.config,
    }),
  });
  const r = await jsonOrThrow<{ firm_mode: FirmMode }>(res, "Create failed");
  return r.firm_mode;
}

export async function updateFirmMode(
  firmId: string,
  name: string,
  config: ModeConfigPayload,
): Promise<FirmMode> {
  const res = await fetch(`${BASE_URL}/api/firms/${firmId}/modes/${encodeURIComponent(name)}`, {
    method: "PATCH",
    credentials: FETCH_CREDS,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  const r = await jsonOrThrow<{ firm_mode: FirmMode }>(res, "Update failed");
  return r.firm_mode;
}

export async function retireFirmMode(firmId: string, name: string): Promise<FirmMode> {
  const res = await fetch(
    `${BASE_URL}/api/firms/${firmId}/modes/${encodeURIComponent(name)}/retire`,
    { method: "POST", credentials: FETCH_CREDS },
  );
  const r = await jsonOrThrow<{ firm_mode: FirmMode }>(res, "Retire failed");
  return r.firm_mode;
}

export async function restoreFirmMode(firmId: string, name: string): Promise<FirmMode> {
  const res = await fetch(
    `${BASE_URL}/api/firms/${firmId}/modes/${encodeURIComponent(name)}/restore`,
    { method: "POST", credentials: FETCH_CREDS },
  );
  const r = await jsonOrThrow<{ firm_mode: FirmMode }>(res, "Restore failed");
  return r.firm_mode;
}

/**
 * Compute the state badge for a list-item row. Pure function so the list
 * component and its tests don't have to duplicate the logic.
 */
export function modeStateLabel(item: ModeListItem): "Built-in" | "Built-in customised" | "Custom" | "Retired" {
  const ov = item.firm_override;
  if (ov && ov.retired_at) return "Retired";
  if (item.is_builtin && item.has_firm_override) return "Built-in customised";
  if (item.is_builtin) return "Built-in";
  return "Custom";
}
