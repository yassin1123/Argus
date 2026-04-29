import type { EvidenceGraph, Session, SessionDetail } from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function createSession(
  query: string,
  title?: string,
  reportMode: string = "general"
): Promise<{ session_id: string; status: string; report_mode?: string }> {
  const res = await fetch(`${BASE_URL}/api/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      title: title?.trim() || query.trim().slice(0, 80),
      report_mode: reportMode,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function generateIntakeQuestions(
  sessionId: string
): Promise<{ questions: Array<Record<string, string>> }> {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/intake/generate`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
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
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/chat`, { cache: "no-store" });
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
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function submitIntakeAnswers(
  sessionId: string,
  answers: Array<{ id: string; answer: string }>
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/intake/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function runSession(sessionId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/run`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function getSession(id: string): Promise<SessionDetail> {
  const res = await fetch(`${BASE_URL}/api/workspaces/${id}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to load session");
  return res.json();
}

export async function getEvidenceGraph(id: string): Promise<EvidenceGraph> {
  const res = await fetch(`${BASE_URL}/api/workspaces/${id}/graph`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to load evidence graph");
  return res.json();
}

export async function listSessions(): Promise<Session[]> {
  const res = await fetch(`${BASE_URL}/api/sessions`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to list sessions");
  return res.json();
}

export async function uploadFile(sessionId: string, file: File): Promise<unknown> {
  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("file", file);
  const res = await fetch(`${BASE_URL}/api/inputs/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
}

export async function submitUrl(sessionId: string, url: string): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/api/inputs/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json();
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
  const res = await fetch(`${BASE_URL}/api/exports/${path}/${sessionId}`);
  if (!res.ok) throw new Error("Export not available");
  return res.blob();
}

/** @deprecated use downloadExport(id, "pdf") */
export async function downloadPDF(sessionId: string): Promise<Blob> {
  return downloadExport(sessionId, "pdf");
}
