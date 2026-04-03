"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AnswerCanvas from "@/components/sessions/AnswerCanvas";
import EvidenceRail from "@/components/sessions/EvidenceRail";
import TrustRail from "@/components/sessions/TrustRail";
import {
  AnswerColumnSkeleton,
  EvidenceRailSkeleton,
  TrustRailSkeleton,
} from "@/components/sessions/WorkspaceSkeletons";
import { Button } from "@/components/ui/Button";
import { downloadExport, type ExportFormat, getSession, runSession } from "@/lib/api";
import type { SessionDetail } from "@/lib/types";

const POLL_MS = 3000;

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function SessionPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportFmt, setExportFmt] = useState<ExportFormat>("pdf");

  const refresh = useCallback(async () => {
    try {
      const data = await getSession(id);
      setSession(data);
      setLoadError(null);
      return data;
    } catch {
      setLoadError("Failed to load session");
      return null;
    }
  }, [id]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const loop = async () => {
      const data = await refresh();
      if (!alive || !data) return;
      if (
        data.status === "complete" ||
        data.status === "failed" ||
        data.status === "insufficient"
      )
        return;
      timer = setTimeout(() => void loop(), POLL_MS);
    };

    void loop();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, refresh]);

  useEffect(() => {
    if (typeof window === "undefined" || !id) return;
    let es: EventSource | null = null;
    const connect = () => {
      try {
        es = new EventSource(`${API_BASE}/api/workspaces/${id}/events`);
        es.onmessage = () => {
          void refresh();
        };
        es.onerror = () => {
          es?.close();
          es = null;
        };
      } catch {
        /* SSE unavailable — polling only */
      }
    };
    if (session?.status === "processing" || session?.status === "pending") {
      connect();
    }
    return () => {
      es?.close();
    };
  }, [id, session?.status, refresh]);

  const handleRun = async () => {
    setRunLoading(true);
    try {
      await runSession(id);
      await refresh();
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setRunLoading(false);
    }
  };

  const handleExport = async () => {
    setExportLoading(true);
    try {
      const blob = await downloadExport(id, exportFmt);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ext = exportFmt === "pptx" ? "pptx" : "pdf";
      a.download = `argus-${exportFmt}-${id.slice(0, 8)}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setLoadError("Export not ready yet");
    } finally {
      setExportLoading(false);
    }
  };

  if (!session && !loadError) {
    return (
      <main className="workspace-grid">
        <div data-area="evidence" className="workspace-rail hidden xl:block">
          <EvidenceRailSkeleton />
        </div>
        <div data-area="answer" className="workspace-answer">
          <AnswerColumnSkeleton />
        </div>
        <div data-area="trust" className="workspace-rail">
          <TrustRailSkeleton />
        </div>
      </main>
    );
  }

  if (loadError && !session) {
    return (
      <main className="mx-auto max-w-lg px-4 py-16">
        <p className="text-argus-danger">{loadError}</p>
        <Button variant="ghost" className="mt-4" onClick={() => router.push("/")}>
          Back home
        </Button>
      </main>
    );
  }

  if (!session) return null;

  const gap = session.gap_report;

  return (
    <main className="workspace-grid">
      <div data-area="evidence" className="workspace-rail">
        <EvidenceRail session={session} />
      </div>
      <div data-area="answer" className="workspace-answer">
        <AnswerCanvas session={session} gap={gap} />
      </div>
      <div data-area="trust" className="workspace-rail">
        <TrustRail
            session={session}
            exportFmt={exportFmt}
            setExportFmt={setExportFmt}
            exportLoading={exportLoading}
            onExport={handleExport}
            runLoading={runLoading}
            onRun={handleRun}
            loadError={loadError}
          />
      </div>
    </main>
  );
}
