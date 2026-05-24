import { describe, expect, it } from "vitest";

import type { NotificationRow } from "@/lib/api/notifications";

import { notificationDeepLink } from "../deepLink";

function row(overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id: "n", recipient_id: "u-1", firm_id: "f-1",
    notification_type: "mention",
    session_id: "s-1",
    source_ref: {},
    actor_id: "u-2",
    summary: "x",
    read: false, read_at: null,
    created_at: new Date().toISOString(),
    email_status: "sent",
    ...overrides,
  };
}

describe("notificationDeepLink", () => {
  it("mention routes to /sessions/{sid}?openComment + #comment hash", () => {
    const link = notificationDeepLink(row({
      notification_type: "mention",
      source_ref: { comment_id: "c-42" },
    }));
    expect(link.href).toContain("/sessions/s-1");
    expect(link.href).toContain("openComment=c-42");
    expect(link.href).toContain("#comment-c-42");
  });

  it("comment_reply routes the same way as mention", () => {
    const link = notificationDeepLink(row({
      notification_type: "comment_reply",
      source_ref: { comment_id: "c-99" },
    }));
    expect(link.href).toContain("openComment=c-99");
  });

  it("review_requested routes to /sessions/{sid}?openReview=1", () => {
    const link = notificationDeepLink(row({
      notification_type: "review_requested",
    }));
    expect(link.href).toBe("/sessions/s-1?openReview=1");
  });

  it("changes_requested + review_approved route to the same surface", () => {
    expect(notificationDeepLink(row({
      notification_type: "changes_requested",
    })).href).toBe("/sessions/s-1?openReview=1");
    expect(notificationDeepLink(row({
      notification_type: "review_approved",
    })).href).toBe("/sessions/s-1?openReview=1");
  });

  it("section_assigned routes to /sessions/{sid}#section-{path}", () => {
    const link = notificationDeepLink(row({
      notification_type: "section_assigned",
      source_ref: { section_path: "synergy_estimate" },
    }));
    expect(link.href).toBe("/sessions/s-1#section-synergy_estimate");
  });

  it("section_needs_review encodes section_path safely", () => {
    const link = notificationDeepLink(row({
      notification_type: "section_needs_review",
      source_ref: { section_path: "frameworks.porters_five_forces" },
    }));
    expect(link.href).toContain("#section-frameworks.porters_five_forces");
  });

  it("engagement_assigned routes to the workspace home for the session", () => {
    expect(notificationDeepLink(row({
      notification_type: "engagement_assigned",
    })).href).toBe("/sessions/s-1");
  });

  it("task_assigned routes to / with the task highlight query", () => {
    const link = notificationDeepLink(row({
      notification_type: "task_assigned",
      session_id: null,
      source_ref: { task_id: "t-7" },
    }));
    expect(link.href).toContain("openTask=t-7");
  });

  it("falls back to session root when source_ref is empty", () => {
    expect(notificationDeepLink(row({
      notification_type: "mention",
      source_ref: {},
    })).href).toBe("/sessions/s-1");
  });
});
