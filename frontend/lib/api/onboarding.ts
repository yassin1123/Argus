// API client for /api/onboarding/* (Phase 5 / Week 24 / Day 2).
// Backs the PilotOnboardingWizard. Mirrors the operator CLI
// (tools/pilot_setup.py) — same backend functions.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FETCH_CREDS: RequestCredentials = "include";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    credentials: FETCH_CREDS,
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    credentials: FETCH_CREDS,
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export interface OnboardingSteps {
  firm_setup: boolean;
  invite_team: boolean;
  upload_library: boolean;
  first_engagement: boolean;
}

export interface OnboardingStatus {
  firm_id: string;
  slug: string;
  name: string;
  steps: OnboardingSteps;
  complete: boolean;
  counts: {
    team_members: number;
    library_documents: number;
    engagements: number;
  };
}

export interface BrandingInput {
  name?: string;
  primary_color?: string;
  secondary_color?: string;
  footer_text?: string;
  logo_url?: string;
}

export interface TeamMemberInput {
  email: string;
  name: string;
  role: "firm_admin" | "firm_member";
}

export interface EngagementInput {
  brief: string;
  mode: string;
  lead_email: string;
  reviewer_email?: string;
  title?: string;
}

export interface PilotBrief {
  id: string;
  mode: string;
  title: string;
  why_good: string;
  research_targets: string[];
  body: string;
}

export function getOnboardingStatus(): Promise<OnboardingStatus> {
  return getJson<OnboardingStatus>("/api/onboarding/status");
}

export function setFirmBranding(input: BrandingInput): Promise<{ ok: boolean; firm_id: string; slug: string }> {
  return postJson("/api/onboarding/firm/branding", input);
}

export function inviteTeamMember(
  input: TeamMemberInput,
): Promise<{ ok: boolean; user_id: string; created: boolean; membership_role: string }> {
  return postJson("/api/onboarding/team", input);
}

export function createFirstEngagement(
  input: EngagementInput,
): Promise<{ ok: boolean; session_id: string; created: boolean; title: string }> {
  return postJson("/api/onboarding/engagement", input);
}

export function getTemplateBriefs(mode?: string): Promise<{ modes: Record<string, PilotBrief[]> }> {
  const qs = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return getJson(`/api/onboarding/briefs${qs}`);
}
