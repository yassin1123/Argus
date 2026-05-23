import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import ActivityFeed from "../ActivityFeed";

const _SAMPLE_EVENTS = [
  {
    id: 1,
    actor_user_id: "u-lead", actor_email: "lead@m.invalid",
    action: "engagement.member_assigned",
    resource_type: "engagement", resource_id: "s1",
    payload: { role: "contributor", target_user_id: "u-alex" },
    created_at: "2026-05-22T12:00:00Z",
  },
  {
    id: 2,
    actor_user_id: "u-alex", actor_email: "alex@m.invalid",
    action: "section.status_changed",
    resource_type: "section_assignment", resource_id: null,
    payload: { section_path: "synergy_estimate",
                old_status: "not_started", new_status: "in_progress" },
    created_at: "2026-05-22T12:30:00Z",
  },
  {
    id: 3,
    actor_user_id: "u-lead", actor_email: "lead@m.invalid",
    action: "auth.login", // NOT a collab event — must be filtered out
    resource_type: null, resource_id: null,
    payload: {},
    created_at: "2026-05-22T11:00:00Z",
  },
  {
    id: 4,
    actor_user_id: "u-alex", actor_email: "alex@m.invalid",
    action: "comment.created",
    resource_type: "comment", resource_id: "c-1",
    payload: { session_id: "s1" },
    created_at: "2026-05-22T13:00:00Z",
  },
];

describe("ActivityFeed", () => {
  beforeEach(() => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ events: _SAMPLE_EVENTS }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders only collaboration-relevant events (filters out auth.login)", async () => {
    render(<ActivityFeed sessionId="s1" />);
    await waitFor(() =>
      expect(screen.getByTestId("activity-event-1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("activity-event-2")).toBeInTheDocument();
    expect(screen.getByTestId("activity-event-4")).toBeInTheDocument();
    // auth.login NOT rendered.
    expect(screen.queryByTestId("activity-event-3")).toBeNull();
  });

  it("surfaces section_path from the payload as a hint", async () => {
    render(<ActivityFeed sessionId="s1" />);
    await waitFor(() =>
      expect(screen.getByTestId("activity-event-2")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("activity-event-2").textContent).toContain(
      "synergy_estimate",
    );
  });

  it("resolves actor name via memberLookup when supplied", async () => {
    const lookup = new Map<string, { name?: string; email?: string }>([
      ["u-lead", { name: "Helena Voss", email: "lead@m.invalid" }],
    ]);
    render(<ActivityFeed sessionId="s1" memberLookup={lookup} />);
    await waitFor(() =>
      expect(screen.getByTestId("activity-event-1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("activity-event-1").textContent).toContain(
      "Helena Voss",
    );
  });
});
