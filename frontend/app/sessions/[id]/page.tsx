"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AnswerCanvas from "@/components/sessions/AnswerCanvas";
import ClientBanner from "@/components/sessions/ClientBanner";
import EvidenceRail from "@/components/sessions/EvidenceRail";
import PipelineTimeline from "@/components/sessions/PipelineTimeline";
import StageInspector from "@/components/sessions/StageInspector";
import TrustRail from "@/components/sessions/TrustRail";
import WorkspaceTabs, { type WorkspaceTab } from "@/components/sessions/WorkspaceTabs";
import {
  AnswerColumnSkeleton,
  EvidenceRailSkeleton,
  TrustRailSkeleton,
} from "@/components/sessions/WorkspaceSkeletons";
import { AuditPanel } from "@/components/Report/AuditPanel";
import DecisionPath from "@/components/Report/DecisionPath";
import EvidenceDrawer from "@/components/Report/EvidenceDrawer";
import EvidenceGraph from "@/components/Report/EvidenceGraph";
import EvidenceObjectsPanel from "@/components/Report/EvidenceObjectsPanel";
import { Button } from "@/components/ui/Button";
import { downloadExport, type ExportFormat, getSession, runSession } from "@/lib/api";
import { SelectionProvider, useSelection } from "@/lib/SelectionContext";
import type { SessionDetail } from "@/lib/types";

const POLL_MS = 3000;

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function WorkspaceInner() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportFmt, setExportFmt] = useState<ExportFormat>("pdf");
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("path");
  const { selectedClaimId, setSelectedClaim } = useSelection();

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
  const evidenceObjects = session.evidence_objects ?? [];
  const reasoningGraph = session.report?.reasoning_graph;
  const graphAvailable =
    session.status === "complete" &&
    !!reasoningGraph &&
    typeof reasoningGraph === "object" &&
    Object.keys(reasoningGraph as Record<string, unknown>).length > 0;
  const claimSupport = session.report?.claim_support ?? [];

  return (
    <>
      <div className="mx-auto max-w-[1600px] px-6 pt-4">
        <ClientBanner session={session} />
        {(session.agent_outputs?.length ?? 0) > 0 ? (
          <PipelineTimeline session={session} />
        ) : null}
      </div>
      <main className="workspace-grid">
        <div data-area="evidence" className="workspace-rail">
          <EvidenceRail session={session} />
        </div>
        <div data-area="answer" className="workspace-answer">
          <WorkspaceTabs
            active={activeTab}
            onChange={setActiveTab}
            evidenceCount={evidenceObjects.length}
            graphAvailable={graphAvailable}
          />
          {activeTab === "path" &&
            (session.report ? (
              <DecisionPath report={session.report} evidenceObjects={evidenceObjects} />
            ) : (
              <div className="rounded-argus-md border border-argus-border-subtle bg-surface p-6 text-sm text-argus-tertiary">
                Decision path appears once the pipeline completes.
              </div>
            ))}
          {activeTab === "answer" && <AnswerCanvas session={session} gap={gap} />}
          {activeTab === "graph" && <EvidenceGraph sessionId={id} />}
          {activeTab === "audit" && (
            <AuditPanel
              verification={session.report?.verification}
              reasoningGraph={reasoningGraph}
              claimSupport={claimSupport}
            />
          )}
          {activeTab === "sources" && <EvidenceObjectsPanel items={evidenceObjects} />}
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
      <footer className="mx-auto mt-2 max-w-[1600px] px-6 pb-6 text-center text-[11px] text-argus-tertiary">
        Generated by Argus · Evidence-grounded
        {session.metadata?.demo ? " · Demo workspace" : ""}
      </footer>

      <StageInspector session={session} />

      <EvidenceDrawer
        open={selectedClaimId !== null}
        claimId={selectedClaimId}
        claimSupport={claimSupport}
        evidenceObjects={evidenceObjects}
        onClose={() => setSelectedClaim(null)}
      />
    </>
  );
}

export default function SessionPage() {
  return (
    <SelectionProvider>
      <WorkspaceInner />
    </SelectionProvider>
  );
}
