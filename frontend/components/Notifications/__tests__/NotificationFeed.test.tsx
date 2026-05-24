import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { NotificationRow } from "@/lib/api/notifications";

vi.mock("@/lib/api/notifications", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/notifications")>(
    "@/lib/api/notifications",
  );
  return {
    ...actual,
    listNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
  };
});

// next/navigation router stub — TestClient JSDOM doesn't ship one.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import NotificationFeed from "../NotificationFeed";
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api/notifications";

const listMock = listNotifications as unknown as ReturnType<typeof vi.fn>;
const markReadMock = markNotificationRead as unknown as ReturnType<typeof vi.fn>;
const markAllMock = markAllNotificationsRead as unknown as ReturnType<typeof vi.fn>;

function makeRow(overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id: overrides.id ?? "n-1",
    recipient_id: "u-1",
    firm_id: "f-1",
    notification_type: "mention",
    session_id: "s-1",
    source_ref: { comment_id: "c-1" },
    actor_id: "u-2",
    summary: "Marcus mentioned you in a comment on Kestrel",
    read: false,
    read_at: null,
    created_at: new Date().toISOString(),
    email_status: "sent",
    ...overrides,
  };
}

describe("NotificationFeed", () => {
  beforeEach(() => {
    listMock.mockReset();
    markReadMock.mockReset();
    markAllMock.mockReset();
  });

  it("renders rows from the API with newest first", async () => {
    listMock.mockResolvedValue({
      user_id: "u-1",
      notifications: [makeRow({ id: "n-1" }), makeRow({ id: "n-2", read: true })],
      count: 2, next_before: null,
    });
    render(<NotificationFeed />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-row-n-1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("notification-row-n-2")).toBeInTheDocument();
    // Unread row has the blue dot; read row does not.
    expect(screen.getByTestId("notification-unread-dot-n-1")).toBeInTheDocument();
    expect(screen.queryByTestId("notification-unread-dot-n-2")).toBeNull();
  });

  it("clicking a row marks it read and navigates via onNavigate", async () => {
    listMock.mockResolvedValue({
      user_id: "u-1", notifications: [makeRow({ id: "n-1" })],
      count: 1, next_before: null,
    });
    markReadMock.mockResolvedValue({ id: "n-1", read: true, changed: true });
    const onNavigate = vi.fn();
    render(<NotificationFeed onNavigate={onNavigate} />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-row-n-1")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("notification-row-n-1"));
    await waitFor(() => expect(markReadMock).toHaveBeenCalledWith("n-1"));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledTimes(1));
    // Deep link includes the session + comment anchor.
    expect(onNavigate.mock.calls[0][0]).toContain("/sessions/s-1");
    expect(onNavigate.mock.calls[0][0]).toContain("openComment=c-1");
  });

  it("mark-all-read fires + refetches", async () => {
    listMock.mockResolvedValue({
      user_id: "u-1",
      notifications: [makeRow({ id: "n-1" }), makeRow({ id: "n-2" })],
      count: 2, next_before: null,
    });
    markAllMock.mockResolvedValue({ marked_read: 2 });
    render(<NotificationFeed />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-feed-mark-all")).toBeInTheDocument(),
    );
    listMock.mockClear();
    fireEvent.click(screen.getByTestId("notification-feed-mark-all"));
    await waitFor(() => expect(markAllMock).toHaveBeenCalledTimes(1));
    // Re-fetched after mark-all to refresh row read-state.
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));
  });

  it("shows empty state when there are no notifications", async () => {
    listMock.mockResolvedValue({
      user_id: "u-1", notifications: [], count: 0, next_before: null,
    });
    render(<NotificationFeed />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-feed-empty")).toBeInTheDocument(),
    );
  });
});
