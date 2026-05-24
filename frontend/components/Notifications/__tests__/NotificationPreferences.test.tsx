import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { PreferencesResponse } from "@/lib/api/notifications";

vi.mock("@/lib/api/notifications", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/notifications")>(
    "@/lib/api/notifications",
  );
  return {
    ...actual,
    getNotificationPreferences: vi.fn(),
    updateNotificationPreferences: vi.fn(),
    resetNotificationPreferences: vi.fn(),
  };
});

import NotificationPreferences from "../NotificationPreferences";
import {
  getNotificationPreferences,
  resetNotificationPreferences,
  updateNotificationPreferences,
} from "@/lib/api/notifications";

const getMock = getNotificationPreferences as unknown as ReturnType<typeof vi.fn>;
const updateMock = updateNotificationPreferences as unknown as ReturnType<typeof vi.fn>;
const resetMock = resetNotificationPreferences as unknown as ReturnType<typeof vi.fn>;

function makeResponse(): PreferencesResponse {
  return {
    user_id: "u-1",
    preferences: [
      { notification_type: "mention", in_app: true, email: true, source: "default" },
      { notification_type: "comment_reply", in_app: true, email: false, source: "default" },
      { notification_type: "section_assigned", in_app: true, email: false, source: "default" },
      { notification_type: "section_needs_review", in_app: true, email: false, source: "default" },
      { notification_type: "engagement_assigned", in_app: true, email: true, source: "default" },
      { notification_type: "task_assigned", in_app: true, email: false, source: "default" },
      { notification_type: "review_requested", in_app: true, email: true, source: "default" },
      { notification_type: "changes_requested", in_app: true, email: true, source: "default" },
      { notification_type: "review_approved", in_app: true, email: true, source: "default" },
    ],
  };
}

describe("NotificationPreferences", () => {
  beforeEach(() => {
    getMock.mockReset();
    updateMock.mockReset();
    resetMock.mockReset();
  });

  it("renders one row per notification type with current toggle state", async () => {
    getMock.mockResolvedValue(makeResponse());
    render(<NotificationPreferences />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-pref-mention")).toBeInTheDocument(),
    );
    // Mention default = (true, true).
    expect(
      (screen.getByTestId("notification-pref-mention-in_app") as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(
      (screen.getByTestId("notification-pref-mention-email") as HTMLInputElement)
        .checked,
    ).toBe(true);
    // Comment-reply default has email off.
    expect(
      (screen.getByTestId("notification-pref-comment_reply-email") as HTMLInputElement)
        .checked,
    ).toBe(false);
  });

  it("toggling a checkbox + Save persists via the update API", async () => {
    getMock.mockResolvedValue(makeResponse());
    updateMock.mockResolvedValue(makeResponse());
    render(<NotificationPreferences />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-pref-mention-email")).toBeInTheDocument(),
    );
    // Flip mention email OFF.
    fireEvent.click(screen.getByTestId("notification-pref-mention-email"));
    fireEvent.click(screen.getByTestId("notification-preferences-save"));
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    const sent = updateMock.mock.calls[0][0] as Array<{
      notification_type: string; in_app: boolean; email: boolean;
    }>;
    expect(sent).toEqual([
      { notification_type: "mention", in_app: true, email: false },
    ]);
  });

  it("reset confirms then wipes via the reset API", async () => {
    getMock.mockResolvedValue(makeResponse());
    resetMock.mockResolvedValue(makeResponse());
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<NotificationPreferences />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-preferences-reset")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("notification-preferences-reset"));
    await waitFor(() => expect(resetMock).toHaveBeenCalledTimes(1));
  });
});
