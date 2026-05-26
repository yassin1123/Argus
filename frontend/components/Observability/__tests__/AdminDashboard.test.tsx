import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { DashboardData } from "@/lib/api/observability";

import AdminDashboard from "../AdminDashboard";

function makeData(overrides: Partial<DashboardData> = {}): DashboardData {
  return {
    hours: 24,
    from: "2026-05-26T10:00:00+00:00",
    to: "2026-05-27T10:00:00+00:00",
    firm_scoped_to: "firm-1",
    volume: {
      started: 8,
      completed: 6,
      failed: 1,
      in_flight: 1,
      success_rate_pct: 85.7,
      by_mode: { m_and_a: { count: 5 }, growth_strategy: { count: 3 } },
    },
    artifacts_generated: 6,
    verification: {
      verdicts: { supported_high: 90, supported_low: 24, weak: 12, contradicted: 3 },
      total: 129,
      supported_pct: 88.4,
      partial_pct: 9.3,
      insufficient_pct: 2.3,
    },
    cost: {
      scope: "firm",
      firm_id: "firm-1",
      total_usd: 3.215,
      call_count: 42,
      engagement_count: 7,
      by_model: [
        {
          model: "claude-sonnet-4-6",
          provider: "anthropic",
          call_count: 28,
          total_usd: 2.4,
          prompt_tokens: 0,
          completion_tokens: 0,
        },
        {
          model: "gpt-4o",
          provider: "openai",
          call_count: 14,
          total_usd: 0.815,
          prompt_tokens: 0,
          completion_tokens: 0,
        },
      ],
    },
    recent_failures: [
      {
        session_id: "sess-fail-1",
        firm_id: "firm-1",
        status: "failed",
        pipeline_state: "failed",
        report_mode: "m_and_a",
        started_at: "2026-05-27T09:50:00+00:00",
        updated_at: "2026-05-27T09:52:00+00:00",
        total_cost_usd: 0.041,
        failed_stage: "research_gathered",
        error_message: "WriterSchemaValidationError: missing valuation_range.method",
      },
    ],
    ...overrides,
  };
}

describe("AdminDashboard", () => {
  it("renders the KPI strip with volume + success rate + total cost", () => {
    render(<AdminDashboard initialData={makeData()} />);
    expect(screen.getByTestId("kpi-started")).toHaveTextContent("8");
    expect(screen.getByTestId("kpi-completed")).toHaveTextContent("6");
    expect(screen.getByTestId("kpi-failed")).toHaveTextContent("1");
    expect(screen.getByTestId("kpi-success-rate")).toHaveTextContent("85.7%");
    expect(screen.getByTestId("kpi-total-cost")).toHaveTextContent("$3.2150");
  });

  it("renders by-mode + by-model tables", () => {
    render(<AdminDashboard initialData={makeData()} />);
    const modes = screen.getByTestId("volume-by-mode");
    expect(modes).toHaveTextContent("m_and_a");
    expect(modes).toHaveTextContent("5");
    const cost = screen.getByTestId("cost-by-model");
    expect(cost).toHaveTextContent("claude-sonnet-4-6");
    expect(cost).toHaveTextContent("$2.4000");
  });

  it("renders the verification quality signal", () => {
    render(<AdminDashboard initialData={makeData()} />);
    const v = screen.getByTestId("verification-block");
    expect(v).toHaveTextContent("88.4% supported");
    expect(v).toHaveTextContent("9.3% partial");
    expect(v).toHaveTextContent("2.3% insufficient");
  });

  it("lists recent failures with clickable trace links", () => {
    render(<AdminDashboard initialData={makeData()} />);
    const failures = screen.getByTestId("recent-failures");
    expect(failures).toHaveTextContent("sess-fai");
    expect(failures).toHaveTextContent("research_gathered");
    expect(failures).toHaveTextContent("$0.0410 burned");
    expect(failures).toHaveTextContent("WriterSchemaValidationError");
  });

  it("shows the no-failures empty state when none in window", () => {
    render(
      <AdminDashboard
        initialData={makeData({ recent_failures: [] })}
      />,
    );
    expect(screen.getByTestId("no-failures")).toBeInTheDocument();
  });
});
