import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { EngagementTrace as EngagementTraceData } from "@/lib/api/trace";

import EngagementTrace from "../EngagementTrace";

function makeTrace(
  overrides: Partial<EngagementTraceData> = {},
): EngagementTraceData {
  return {
    session_id: "sess-1",
    firm_id: "firm-1",
    run_id: null,
    status: "complete",
    pipeline_state: "deliverable_ready",
    report_mode: "m_and_a",
    started_at: "2026-05-26T10:00:00+00:00",
    ended_at: "2026-05-26T10:01:28+00:00",
    wall_ms: 88_000,
    total_cost_usd: 0.452,
    timeline: [
      {
        stage: "pipeline_start",
        at: "2026-05-26T10:00:00+00:00",
        duration_ms: null,
        detail: "status=processing",
        ok: true,
      },
      {
        stage: "complete",
        at: "2026-05-26T10:01:28+00:00",
        duration_ms: 88_000,
        detail: "unsupported_claims=1",
        ok: true,
      },
    ],
    stage_rollups: [
      {
        agent: "writer",
        call_count: 1,
        cost_usd: 0.156,
        prompt_tokens: 6000,
        completion_tokens: 8000,
        error_count: 0,
      },
      {
        agent: "verifier",
        call_count: 1,
        cost_usd: 0.034,
        prompt_tokens: 3800,
        completion_tokens: 1500,
        error_count: 0,
      },
    ],
    llm_calls: [],
    verification: {
      assessments_total: 27,
      verdict_distribution: {
        supported_high: 18,
        weak: 2,
        contradicted: 1,
      },
    },
    retrieval: {
      evidence_count: 42,
      evidence_by_source: { sec_filing: 20, transcripts: 12, news: 10 },
      followup_query_count: 0,
    },
    versions: [],
    failure: {
      failed: false,
      failed_stage: null,
      last_successful_stage: null,
      error_message: null,
      error_kind: null,
      writer_schema_failure: null,
    },
    gaps: [],
    ...overrides,
  };
}

describe("EngagementTrace", () => {
  it("renders header totals + per-stage cost rollups", () => {
    const trace = makeTrace();
    render(<EngagementTrace sessionId="sess-1" initialTrace={trace} />);
    expect(screen.getByTestId("trace-status")).toHaveTextContent("complete");
    expect(screen.getByTestId("trace-mode")).toHaveTextContent("m_and_a");
    expect(screen.getByTestId("trace-total-cost")).toHaveTextContent("$0.4520");
    expect(screen.getByTestId("trace-wall-time")).toHaveTextContent("88.0s");
    // Stage rollup row visible.
    const rollups = screen.getByTestId("trace-stage-rollups");
    expect(rollups).toHaveTextContent("writer");
    expect(rollups).toHaveTextContent("$0.1560");
  });

  it("renders verification verdict distribution + retrieval breakdown", () => {
    const trace = makeTrace();
    render(<EngagementTrace sessionId="sess-1" initialTrace={trace} />);
    const verdicts = screen.getByTestId("trace-verdicts");
    expect(verdicts).toHaveTextContent("supported_high");
    expect(verdicts).toHaveTextContent("18");
    const retrieval = screen.getByTestId("trace-retrieval");
    expect(retrieval).toHaveTextContent("sec_filing");
    expect(retrieval).toHaveTextContent("42");
  });

  it("surfaces the failure banner with stage + error for a failed engagement", () => {
    const failed = makeTrace({
      status: "failed",
      pipeline_state: "failed",
      failure: {
        failed: true,
        failed_stage: "research_gathered",
        last_successful_stage: "research_gathered",
        error_message:
          "WriterSchemaValidationError: missing required field",
        error_kind: "schema_validation_failed",
        writer_schema_failure: {
          schema_name: "WriterReportPayload",
          field_path: "valuation_range.method",
        },
      },
    });
    render(<EngagementTrace sessionId="sess-1" initialTrace={failed} />);
    expect(screen.getByTestId("trace-failure")).toBeInTheDocument();
    expect(screen.getByTestId("trace-failed-stage")).toHaveTextContent(
      "research_gathered",
    );
    expect(screen.getByTestId("trace-failure")).toHaveTextContent(
      "WriterSchemaValidationError",
    );
    expect(screen.getByTestId("trace-failure")).toHaveTextContent(
      "valuation_range.method",
    );
  });

  it("renders the data-gaps panel when sections are missing", () => {
    const partial = makeTrace({
      gaps: ["verification_metrics_missing", "retrieval_metrics_missing"],
    });
    render(<EngagementTrace sessionId="sess-1" initialTrace={partial} />);
    const gaps = screen.getByTestId("trace-gaps");
    expect(gaps).toHaveTextContent("verification metrics missing");
    expect(gaps).toHaveTextContent("retrieval metrics missing");
  });
});
