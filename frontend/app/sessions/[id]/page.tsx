"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import ArtifactsRail from "@/components/workspace/ArtifactsRail";
import Conversation from "@/components/workspace/Conversation";
import MemoEditor from "@/components/workspace/MemoEditor";
import SourceRail from "@/components/workspace/SourceRail";
import WorkspaceTopBar from "@/components/workspace/WorkspaceTopBar";
import { getSession } from "@/lib/api";
import { SelectionProvider } from "@/lib/SelectionContext";
import type { SessionDetail } from "@/lib/types";

const POLL_MS = 3000;
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function WorkspaceInner() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showWork, setShowWork] = useState(false);
  const [collapseSource, setCollapseSource] = useState(false);
  const [collapseArtifacts, setCollapseArtifacts] = useState(false);
  // Phase 9: when an artifact is open, the center pane becomes the editor.
  const [openArtifactId, setOpenArtifactId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getSession(id);
      setSession(data);
      setLoadError(null);
      return data;
    } catch {
      setLoadError("Failed to load engagement");
      return null;
    }
  }, [id]);

  // Polling — continues while the pipeline is running OR while the verifier
  // is still streaming per-claim NLI results into structured_answer (so
  // citations resolve from "Verifying…" to their final state in the UI).
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loop = async () => {
      const data = await refresh();
      if (!alive || !data) return;
      const verificationState = data.report?.structured_answer?.verification_state;
      const stillVerifying =
        verificationState === "pending" || verificationState === "verifying";
      const pipelineDone =
        data.status === "complete" ||
        data.status === "failed" ||
        data.status === "insufficient";
      if (pipelineDone && !stillVerifying) return;
      timer = setTimeout(() => void loop(), POLL_MS);
    };
    void loop();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, refresh]);

  // SSE for live progress — open while the pipeline is running OR while the
  // verifier is still streaming so citations flip to verified states in real time.
  const verificationStreaming =
    session?.report?.structured_answer?.verification_state === "verifying" ||
    session?.report?.structured_answer?.verification_state === "pending";
  useEffect(() => {
    if (typeof window === "undefined" || !id) return;
    let es: EventSource | null = null;
    if (session?.status === "processing" || session?.status === "pending" || verificationStreaming) {
      try {
        es = new EventSource(`${API_BASE}/api/workspaces/${id}/events`);
        es.onmessage = () => void refresh();
        es.onerror = () => {
          es?.close();
          es = null;
        };
      } catch {
        /* SSE blocked */
      }
    }
    return () => es?.close();
  }, [id, session?.status, verificationStreaming, refresh]);

  if (!session && !loadError) {
    return (
      <>
        <header className="argus-topbar">
          <span className="text-[11px] text-argus-tertiary">Loading engagement…</span>
        </header>
        <div className="argus-workbench">
          <div className="argus-pane-source" />
          <div className="argus-pane-center" />
          <div className="argus-pane-artifacts" />
        </div>
      </>
    );
  }

  if (loadError && !session) {
    return (
      <main className="mx-auto max-w-lg px-4 py-16">
        <p className="text-argus-contested">{loadError}</p>
        <button
          onClick={() => router.push("/")}
          className="mt-4 rounded-sm border border-argus-border-moderate bg-surface px-3 py-1 text-[12px] hover:border-argus-primary"
        >
          Back to engagements
        </button>
      </main>
    );
  }

  if (!session) return null;

  return (
    <>
      <WorkspaceTopBar
        session={session}
        showWork={showWork}
        onToggleShowWork={() => setShowWork((v) => !v)}
        collapseSource={collapseSource}
        onToggleSource={() => setCollapseSource((v) => !v)}
        collapseArtifacts={collapseArtifacts}
        onToggleArtifacts={() => setCollapseArtifacts((v) => !v)}
      />
      <div
        className="argus-workbench"
        data-collapse-source={collapseSource}
        data-collapse-artifacts={collapseArtifacts}
      >
        <SourceRail session={session} />
        {openArtifactId ? (
          <div className="argus-pane-center">
            <MemoEditor
              artifactId={openArtifactId}
              onClose={() => setOpenArtifactId(null)}
            />
          </div>
        ) : (
          <Conversation session={session} showWork={showWork} />
        )}
        <ArtifactsRail
          session={session}
          onOpenArtifact={(id) => setOpenArtifactId(id)}
        />
      </div>
    </>
  );
}

export default function WorkspacePage() {
  return (
    <SelectionProvider>
      <WorkspaceInner />
    </SelectionProvider>
  );
}
