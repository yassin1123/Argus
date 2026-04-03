import {
  AnswerColumnSkeleton,
  EvidenceRailSkeleton,
  TrustRailSkeleton,
} from "@/components/sessions/WorkspaceSkeletons";

export default function Loading() {
  return (
    <main className="workspace-grid">
      <div data-area="evidence" className="workspace-rail hidden lg:block">
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
