export type EngagementRole = "lead" | "member" | "viewer";

export interface Session {
  id: string;
  title: string;
  query: string;
  status: "draft" | "pending" | "processing" | "complete" | "failed" | "insufficient";
  created_at: string;
  updated_at: string;
  gap_report?: GapReport;
  pipeline_state?: string;
  report_mode?: string;
  evidence_count?: number;
  /** Latest report recommendation excerpt for session list cards */
  recommendation_preview?: string | null;
  /** The current viewer's role on this engagement, if any. */
  my_role?: EngagementRole | null;
  /** Demo / engagement framing in metadata (set by the demo seeder). */
  metadata?: Record<string, unknown> & {
    client_label?: string;
    engagement_type?: string;
    demo?: boolean;
    stub?: boolean;
  };
}

export interface EngagementMember {
  user_id: string;
  email: string;
  full_name: string;
  role: EngagementRole;
  added_at?: string | null;
}

export type TrustLevel = "firm_vetted" | "credible_external" | "web_general" | "contested";
export type SourceScope = "engagement" | "firm";

export interface SourceItem {
  id: string;
  session_id: string | null;
  filename: string;
  file_type: string;
  trust_level: TrustLevel;
  scope: SourceScope;
  notes: string;
  source_url: string | null;
  original_size: number | null;
  blob_id: string | null;
  chunk_count: number;
  created_at: string | null;
}

export interface ChunkSearchResult {
  id: string;
  session_id: string | null;
  content: string;
  source_type: string;
  position: number;
  page: number | null;
  slide: number | null;
  timestamp_str: string | null;
  speaker: string | null;
  section_heading: string | null;
  source_filename: string;
  source_url: string | null;
  trust_level: TrustLevel;
  score: number;
  fused_score?: number;
  rerank_score?: number;
  snippet?: string | null;
}

export interface ChunkSearchResponse {
  mode: "hybrid" | "vector" | "keyword";
  vector_count: number;
  keyword_count: number;
  results: ChunkSearchResult[];
}

export interface GapReport {
  title?: string;
  missing_evidence?: string[];
  suggested_searches?: string[];
  contradictions?: string[];
  notes?: string;
}

export interface AgentOutput {
  id: string;
  agent_name:
    | "planner"
    | "researcher"
    | "analyst"
    | "critic"
    | "analyst_revision"
    | "critic_post_revision"
    | "verifier"
    | "writer";
  input: string | null;
  output: string;
  duration_ms: number | null;
  token_count: number | null;
  created_at: string;
}

export interface EvidenceBundleItem {
  kind?: string;
  chunk_id?: string;
  quote?: string;
  filename?: string;
  file_type?: string;
  similarity?: number;
  source_url?: string;
  url?: string;
  title?: string;
  snippet?: string;
  task_id?: number;
  finding_summary?: string;
  evidence_id?: string;
  source_type?: string;
}

export interface EvidenceObjectRow {
  id: string;
  session_id?: string;
  task_id?: number | null;
  claim?: string;
  quote?: string;
  source_title?: string;
  source_url?: string;
  source_date?: string | null;
  source_type?: string;
  source_score?: number;
  confidence?: string;
  is_inference?: boolean;
  created_at?: string | null;
  /**
   * Source-type-specific breadcrumb data (Phase 2 / Week 5 / Day 4).
   * For source_type='firm_library' this carries:
   *   firm_content_id, firm_library_title, category, intended_modes,
   *   sector_tags, section.
   * Other source types may populate it as enrichments arrive.
   */
  metadata?: Record<string, unknown>;
}

export interface ExecutiveInsightItem {
  text?: string;
  claim_ids?: string[];
}

export interface KeyRiskStructuredItem {
  text?: string;
  claim_ids?: string[];
}

export interface ConsultingPayload {
  executive_insights?: ExecutiveInsightItem[];
  recommendation_claim_ids?: string[];
  key_risks_structured?: KeyRiskStructuredItem[];
  decision_criteria?: Array<Record<string, unknown>>;
  options_matrix?: Array<Record<string, unknown>>;
  kill_criteria?: string[];
  what_would_change_our_mind?: string;
  evidence_ledger_summary?: string;
}

export interface RetrievalTaskSnapshot {
  task_id?: number;
  question?: string;
  hits?: Array<{
    chunk_id?: string;
    text?: string;
    chunk_index?: number;
    similarity?: number;
    filename?: string;
    file_type?: string;
    page?: number | null;
    source_url?: string | null;
  }>;
}

export interface ClaimSupportRow {
  claim_id?: string;
  claim_text?: string;
  evidence_object_ids?: string[];
  support_type?: string;
  verifier_verdict?: string | null;
  contradiction_flag?: boolean;
  staleness_hint?: string;
  entailment_score?: number;
  weak_or_unsupported?: boolean;
  nli_label?: string;
  nli_confidence?: number;
  // Phase 1 / Week 2 / Day 3 ensemble columns. Populated whenever
  // ensemble_enrich.py runs (every pipeline run regardless of the
  // ARGUS_USE_ENSEMBLE_VERDICT flag); the flag only controls whether
  // downstream gates *read* them.
  numeric_overlap_score?: number | null;
  numeric_overlap_missing?: string[];
  entity_overlap_score?: number | null;
  entity_overlap_missing?: string[];
  ensemble_verdict?:
    | "supported_high"
    | "supported_low"
    | "weak"
    | "unsupported"
    | "contradicted"
    | string
    | null;
  ensemble_reason?: string | null;
}

export interface Report {
  id: string;
  session_id: string;
  recommendation: string;
  confidence_level: string;
  summary: string;
  key_reasons: string[];
  risks: string[];
  counterarguments: string[];
  next_steps: string[];
  sources: { title: string; type: string }[];
  caveats: string;
  evidence_bundle?: EvidenceBundleItem[];
  raw_output?: string | null;
  created_at: string;
  verification?: Record<string, unknown>;
  evidence_count?: number;
  unsupported_claim_count?: number;
  consulting_payload?: ConsultingPayload;
  reasoning_graph?: Record<string, unknown>;
  claim_support?: ClaimSupportRow[];
  structured_answer?: StructuredAnswer | null;
}

export type StructuredConfidence = "high" | "medium" | "contested";
export type NliLabel = "entailment" | "neutral" | "contradiction" | "skipped";

export interface NliResult {
  chunk_id: string;
  label: NliLabel;
  score: number;
}

export interface GroundedClaim {
  text: string;
  chunk_ids: string[];
  confidence: StructuredConfidence;
  notes?: string;
  nli_results?: NliResult[];
}

export interface StructuredSection {
  heading?: string;
  text: string;
  claims: GroundedClaim[];
}

export type VerificationState = "pending" | "verifying" | "complete";

export interface StructuredAnswer {
  tldr: string;
  sections: StructuredSection[];
  caveats: string;
  validation_notes: string[];
  verification_state?: VerificationState;
}

// ---- Artifacts ---------------------------------------------------------

export type ArtifactType = "memo" | "deck" | "model" | "chart";
export type ArtifactStatus = "draft" | "review" | "final";

export interface Artifact {
  id: string;
  engagement_id: string;
  type: ArtifactType;
  title: string;
  status: ArtifactStatus;
  document_json: Record<string, unknown> | null;
  source_report_id: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkspacePresentationMeta {
  title: string;
  status_label: string;
  report_mode_label: string;
  pipeline_stage_label: string;
  source_count: number;
  file_count: number;
}

export interface WorkspacePresentationAnswer {
  headline: string;
  summary: string;
  confidence_display: string;
  next_steps_count: number;
  key_points: string[];
}

export interface WorkspacePresentationTrust {
  confidence_label: string;
  verification_summary: string;
  evidence_strength_label: string;
  caveats_preview: string;
  unsupported_claims_count: number;
  verification_overall_label?: string;
  contradiction_severity_label?: string;
  what_capped_confidence?: string;
  claims_verified_hint?: string;
}

export interface WorkspacePresentationEvidenceItem {
  ordinal: number;
  source_label: string;
  excerpt: string;
  kind_label: string;
}

export interface WorkspacePresentationEvidence {
  total: number;
  items: WorkspacePresentationEvidenceItem[];
}

export interface WorkspacePresentation {
  meta: WorkspacePresentationMeta;
  answer: WorkspacePresentationAnswer | null;
  trust: WorkspacePresentationTrust | null;
  evidence: WorkspacePresentationEvidence;
}

export interface IntakeQuestionRow {
  id: string;
  question: string;
  why?: string;
  input_type?: string;
  placeholder?: string;
}

export interface EvidenceGraphNode {
  id: string;
  type: "claim" | "evidence" | "source";
  label: string;
  verifier_verdict?: string;
  support_type?: string;
  weak?: boolean;
  in_recommendation?: boolean;
  evidence_count?: number;
  confidence?: string;
  is_inference?: boolean;
  source_title?: string;
  source_url?: string;
  source_type?: string;
  quote?: string;
  url?: string;
}

export interface EvidenceGraphEdge {
  from: string;
  to: string;
  kind: "cites" | "supports" | "contradicts";
}

export interface EvidenceGraphStats {
  claims: number;
  evidence: number;
  sources: number;
  supported: number;
  weak: number;
  unsupported: number;
}

export interface EvidenceGraph {
  nodes: EvidenceGraphNode[];
  edges: EvidenceGraphEdge[];
  stats: EvidenceGraphStats;
}

export interface SessionDetail extends Session {
  intake_questions?: IntakeQuestionRow[];
  intake_answers?: Array<{ id: string; answer: string }>;
  agent_outputs: AgentOutput[];
  report: Report | null;
  uploaded_files: { id: string; filename: string; file_type: string }[];
  metadata?: Record<string, unknown> & {
    retrieval_hits?: RetrievalTaskSnapshot[];
    research_branches?: Array<{ id?: string; questions?: string[]; evidence_added_count?: number }>;
    research_contradictions?: string[];
    contradiction_severity?: number;
    pipeline_trace?: Array<{ event?: string; detail?: string; at?: string }>;
    /** Engagement framing — populated by the demo seeder. */
    client_label?: string;
    engagement_type?: string;
    demo?: boolean;
    stub?: boolean;
  };
  gap_report?: GapReport;
  evidence_objects?: EvidenceObjectRow[];
  /** From GET /api/workspaces/:id — server-side labels for rails */
  presentation?: WorkspacePresentation;
}
